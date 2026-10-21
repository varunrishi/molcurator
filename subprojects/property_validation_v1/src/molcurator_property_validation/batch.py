"""Batch interface for generated molecules, reports and SLURM preparation."""
import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import re
import uuid

from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate
from .chem.calculations import safe_id
from .chem.settings import active_settings, load_settings
from .chem.tracking import atomic_json, native_path


def read_candidates(path, format="auto"):
    path = Path(path)
    format = ("csv" if path.suffix.lower() == ".csv" else "smi") if format == "auto" else format
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if format == "csv":
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"id", "smiles"} <= set(reader.fieldnames):
                raise ValueError("CSV requires id and smiles headers")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed CSV row {reader.line_num}")
                rows.append(row)
        else:
            for line_number, line in enumerate(handle, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                fields = line.split()
                if len(fields) > 2:
                    raise ValueError(f"SMILES line {line_number} must contain SMILES and optional ID")
                rows.append(dict(smiles=fields[0], id=fields[1] if len(fields) == 2 else f"mol{len(rows)+1:06d}"))
    candidates = []
    seen = set()
    for row in rows:
        cid = safe_id(row["id"].strip())
        if cid in seen:
            raise ValueError(f"duplicate candidate ID: {cid}")
        seen.add(cid)
        smiles = row["smiles"].strip()
        if not smiles:
            raise ValueError(f"empty SMILES for {cid}")
        candidates.append(Candidate(id=cid, smiles=smiles,
            parent_smiles=(row.get("parent_smiles") or smiles).strip(),
            round=int(row.get("round") or 1), generator=(row.get("generator") or "batch_input").strip()))
    if not candidates:
        raise ValueError("input contains no molecules")
    return candidates


@contextmanager
def run_lock(directory):
    """OS advisory lock releases after interruption without stale lock removal."""
    handle = (directory / ".run.lock").open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("another batch process holds this run directory") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("another batch process holds this run directory") from exc
        locked = True
        yield
    finally:
        if locked and os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def check_allocation(settings, orca):
    if not orca:
        return
    cpus = os.environ.get("SLURM_CPUS_PER_TASK")
    if cpus and settings.orca_nprocs > int(cpus):
        raise ValueError("orca_nprocs exceeds SLURM_CPUS_PER_TASK")
    memory = os.environ.get("SLURM_MEM_PER_NODE")
    if memory and settings.orca_nprocs * settings.orca_maxcore_mb > int(memory):
        raise ValueError("ORCA nominal memory exceeds SLURM_MEM_PER_NODE; reserve overhead too")


def run_batch(args):
    from .reporting import generate_report, require_plotting
    if not args.no_plots:
        require_plotting()
    candidates = read_candidates(args.input, args.format)
    settings = load_settings()
    check_allocation(settings, args.orca)
    target = PropertyTarget(name="homo_lumo_gap", min=args.min_gap if args.min_gap is not None else 0,
                            max=args.max_gap, units="eV")
    qm = QMSettings(backend="orca", functional=args.functional, basis=args.basis)
    if any(value is not None and not math.isfinite(value) for value in (args.min_gap, args.max_gap)):
        raise ValueError("gap bounds must be finite")
    if args.orca and any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+*(),./-]*", token)
                         for token in (qm.functional, qm.basis)):
        raise ValueError("functional and basis must be single ORCA keyword tokens")
    if args.orca_limit is not None and not args.orca:
        raise ValueError("--orca-limit requires --orca")
    if args.orca_limit is not None and args.orca_limit < 0:
        raise ValueError("--orca-limit must be nonnegative")
    dataset = [candidate.model_dump(mode="json") for candidate in candidates]
    fingerprint = hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest()
    output = native_path(args.out)
    if args.resume:
        if not (output / "results.json").is_file():
            raise ValueError("--resume requires an existing batch results.json")
    else:
        output.mkdir(parents=True, exist_ok=False)
    with run_lock(output):
        if args.resume:
            old = json.loads((output / "results.json").read_text())
            if old.get("input_fingerprint") != fingerprint:
                raise ValueError("resume input differs; use a new output directory")
            history = output / "history"
            history.mkdir(exist_ok=True)
            atomic_json(history / (old["invocation_id"] + ".json"), old)
        state = dict(schema_version=1, invocation_id=uuid.uuid4().hex,
            input_path=str(Path(args.input).resolve()), input_fingerprint=fingerprint,
            started_at=datetime.now(timezone.utc).isoformat(), run_status="running",
            settings=settings.model_dump(), target=target.model_dump(mode="json"),
            qm=qm.model_dump(mode="json") if args.orca else None, orca_limit=args.orca_limit,
            rows=[dict(candidate=c, prediction=None, qm_result=None,
                       orca_selection="pending" if args.orca else "not_requested") for c in dataset])

        def checkpoint():
            atomic_json(output / "results.json", state)

        checkpoint()
        selected_count = 0
        exit_code = 0
        token = active_settings.set(settings)
        try:
            for candidate, row in zip(candidates, state["rows"]):
                prediction = predict([candidate], target, output / "xyz")[0]
                row["prediction"] = prediction.model_dump(mode="json")
                checkpoint()
                if prediction.status is Status.failed:
                    exit_code = 1
                    if args.orca:
                        row["orca_selection"] = "prediction_failed"
                elif args.orca:
                    in_window = (target.min is None or prediction.value >= target.min) and (
                        target.max is None or prediction.value <= target.max)
                    within_limit = args.orca_limit is None or selected_count < args.orca_limit
                    if in_window and within_limit:
                        selected_count += 1
                        row["orca_selection"] = "selected"
                        checkpoint()
                        result = validate([prediction], target, qm)[0]
                        row["qm_result"] = result.model_dump(mode="json")
                        if result.status is Status.failed:
                            exit_code = 1
                    else:
                        row["orca_selection"] = "outside_window" if not in_window else "limit_reached"
                checkpoint()
            state["run_status"] = "completed_with_failures" if exit_code else "completed"
        except KeyboardInterrupt:
            state["run_status"] = "interrupted"
            exit_code = 130
        except Exception as exc:
            state.update(run_status="error", error=f"{type(exc).__name__}: {exc}")
            exit_code = 1
        finally:
            active_settings.reset(token)
            state["finished_at"] = datetime.now(timezone.utc).isoformat()
            checkpoint()
            generate_report(output, plots=not args.no_plots)
        print(f"{state['run_status']}: {output / 'report.md'}")
        return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="predict CSV or SMILES input and write reports")
    run.add_argument("input", type=Path)
    run.add_argument("--format", choices=("auto", "csv", "smi"), default="auto")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--orca", action="store_true", help="validate selected successful xTB predictions")
    run.add_argument("--orca-limit", type=int, help="maximum selected ORCA inputs per invocation, including cache hits")
    run.add_argument("--min-gap", type=float, help="minimum xTB gap for ORCA selection in eV")
    run.add_argument("--max-gap", type=float, help="maximum xTB gap for ORCA selection in eV")
    run.add_argument("--functional", default="B3LYP")
    run.add_argument("--basis", default="def2-SVP")
    run.add_argument("--no-plots", action="store_true", help="write CSV/JSON/Markdown without matplotlib")
    report = commands.add_parser("report", help="regenerate reports without running chemistry")
    report.add_argument("run_dir", type=Path)
    report.add_argument("--no-plots", action="store_true")
    slurm = commands.add_parser("slurm", help="generate a SLURM script; submit only with --submit")
    slurm.add_argument("--config", type=Path, required=True)
    slurm.add_argument("--script", type=Path, required=True)
    slurm.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_batch(args)
        if args.command == "report":
            from .reporting import generate_report
            generate_report(native_path(args.run_dir), plots=not args.no_plots)
            print(native_path(args.run_dir) / "report.md")
            return 0
        from .slurm import prepare
        return prepare(args.config, args.script, submit=args.submit)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
