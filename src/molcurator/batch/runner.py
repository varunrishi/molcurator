"""Checkpointed batch execution independent of command-line parsing."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from molcurator.schemas import PropertyTarget, QMSettings, Status
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate
from .inputs import read_candidates
from .runtime import check_allocation, run_lock
from molcurator.chem.settings import active_settings, load_settings
from molcurator.chem.fileio import atomic_json, native_path


def run_batch(args, *, predict_fn=None, validate_fn=None):
    predict_fn = predict if predict_fn is None else predict_fn
    validate_fn = validate if validate_fn is None else validate_fn
    from .reporting import generate_report, require_plotting
    if args.plots:
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
                prediction = predict_fn([candidate], target, output / "xyz")[0]
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
                        result = validate_fn([prediction], target, qm)[0]
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
            generate_report(output, plots=args.plots)
        print(f"{state['run_status']}: {output / 'report.md'}")
        return exit_code
