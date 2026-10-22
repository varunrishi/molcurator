"""Check Python imports and chemistry backends; optional real one-molecule smoke test.

xTB runs in-process through tblite (a Python package), so it needs no binary. ORCA is
found through ORCA_BIN (environment or .env), else `orca` on PATH. ORCA on more than one core
(orca_nprocs > 1) also needs Open MPI: OPENMPI_HOME, else mpirun on PATH.
"""
import argparse
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Also works before installation, so missing dependencies can be reported clearly.
sys.path.insert(0, str(ROOT / "src"))

MODULES = ("rdkit", "pydantic", "yaml", "molcurator.tools.predict", "molcurator.tools.validate",
           "molcurator.batch.cli")
BACKEND_MODULES = {"xtb": ("tblite", "tblite.interface"), "orca": ("opi",)}


def _env(env_file: Path) -> None:
    """Fill in ORCA_BIN, MOLCURATOR_CHEM_CONFIG and MOLCURATOR_QC_TIMEOUT_S from .env;
    variables already set in the process win."""
    from dotenv import dotenv_values
    for key, value in dotenv_values(env_file).items() if env_file.is_file() else ():
        if key in ("ORCA_BIN", "OPENMPI_HOME", "MOLCURATOR_CHEM_CONFIG", "MOLCURATOR_QC_TIMEOUT_S") and value \
                and not os.environ.get(key):
            os.environ[key] = value


def _orca_check() -> dict:
    value = os.environ.get("ORCA_BIN") or "orca"
    executable = shutil.which(value)
    ok = bool(executable and Path(executable).is_file() and os.access(executable, os.X_OK))
    detail = (f"{executable} (runtime not tested)" if ok else
              f"Not executable or not found: {value}. Set ORCA_BIN to an absolute executable path or load its module.")
    return {"name": "ORCA_BIN", "ok": ok, "detail": detail}


def _mpi_check(nprocs: int) -> dict:
    """Open MPI is required only when the settings ask for more than one ORCA core."""
    from molcurator.chem.orca import _find_mpirun, _mpi_defaults
    try:
        mpirun = _find_mpirun(os.environ.get("OPENMPI_HOME") or None)
    except ValueError as exc:
        return {"name": "Open MPI", "ok": nprocs == 1,
                "detail": "not found; only needed for orca_nprocs > 1" if nprocs == 1 else str(exc)}
    settings = " ".join(f"{k}={v}" for k, v in _mpi_defaults(mpirun).items())
    return {"name": "Open MPI", "ok": True, "detail": f"{mpirun} (orca_nprocs={nprocs}; defaults: {settings})"}


def preflight(backend: str = "all", env_file: Path | None = None) -> dict:
    _env(env_file if env_file is not None else ROOT / ".env")
    backends = ("xtb", "orca") if backend == "all" else (backend,)
    checks = [{"name": "Python >= 3.11", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]}]
    for name in (*MODULES, *(m for b in backends for m in BACKEND_MODULES[b])):
        try:
            module = importlib.import_module(name)
            checks.append({"name": name, "ok": True, "detail": str(getattr(module, "__version__", "import OK"))})
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            checks.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
    nprocs = 1
    try:
        from molcurator.chem.settings import load_settings
        settings = load_settings()
        nprocs = settings.orca_nprocs
        checks.append({"name": "chemistry settings", "ok": True, "detail": settings.model_dump()})
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        checks.append({"name": "chemistry settings", "ok": False, "detail": str(exc)})
    if "orca" in backends:
        checks.append(_orca_check())
        checks.append(_mpi_check(nprocs))
    return {"ok": all(c["ok"] for c in checks), "backend": backend, "checks": checks, "runtime_tested": False}


def smoke(backend: str, output: Path, resume: bool = False) -> dict:
    """Ethanol through the real tools: GFN2-xTB PREDICT and/or a B3LYP/def2-SVP ORCA VALIDATE."""
    from molcurator.chem.geometry import (
        charge_multiplicity_comment,
        lowest_ff_conformer,
        with_comment,
    )
    from molcurator.schemas import (
        Candidate,
        Prediction,
        PropertyTarget,
        QMSettings,
        Status,
    )
    from molcurator.tools.predict import predict
    from molcurator.tools.validate import validate
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=resume)
    candidate = Candidate(id="ethanol", smiles="CCO", parent_smiles="CCO", round=1, generator="preflight")
    target = PropertyTarget(name="homo_lumo_gap", min=0)
    result = {"backend": backend, "predictions": [], "qm_results": [], "ok": False}
    if backend in ("xtb", "all"):
        predictions = predict([candidate], target, output / "xyz")
        result["predictions"] = [p.model_dump(mode="json") for p in predictions]
    else:
        # An ORCA-only check must not need xTB: use the force-field geometry directly.
        xyz, report = lowest_ff_conformer(candidate.smiles)
        path = output / "xyz" / "ethanol.xyz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(with_comment(xyz, charge_multiplicity_comment(0, 1)))
        result["geometry_report"] = report
        # The placeholder value only satisfies the Prediction contract; it is not an xTB result.
        predictions = [Prediction(candidate_id=candidate.id, status=Status.ok, value=0, xyz_path=path)]
    predicted = predictions[0].status is Status.ok
    if backend in ("orca", "all") and predicted:
        values = validate(predictions, target, QMSettings())
        result["qm_results"] = [r.model_dump(mode="json") for r in values]
        result["ok"] = values[0].status is Status.ok
    else:
        result["ok"] = predicted
    records = list((output / "xyz").glob("calculations/*/*.json"))
    result["calculations_recorded"] = sum(p.name in ("predict.json", "validate.json") for p in records)
    (output / "preflight-smoke.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("xtb", "orca", "all"), default="all")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="run real chemistry on an allocated compute node")
    parser.add_argument("--resume", action="store_true", help="reuse an existing smoke directory")
    parser.add_argument("--out", type=Path, help="smoke output directory (new unless --resume)")
    args = parser.parse_args()
    if args.smoke and args.out is None:
        parser.error("--smoke requires --out")
    if args.resume and not args.smoke:
        parser.error("--resume requires --smoke")
    report = preflight(args.backend, args.env_file)
    if args.smoke and report["ok"]:
        try:
            report["smoke"] = smoke(args.backend, args.out, args.resume)
            report["runtime_tested"] = report["smoke"].get("calculations_recorded", 1) > 0
            report["ok"] = report["smoke"]["ok"]
        except Exception as exc:  # noqa: BLE001 - reported in the preflight result
            report.update(ok=False, smoke_error=f"{type(exc).__name__}: {exc}")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for item in report["checks"]:
            print(f"[{'OK' if item['ok'] else 'FAIL'}] {item['name']}: {item['detail']}")
        if args.smoke:
            print("Workflow smoke:", "PASS" if report.get("smoke", {}).get("ok") else "FAILED or not run")
            if report.get("smoke"):
                print("Calculations recorded:", report["smoke"].get("calculations_recorded", "unknown"))
        else:
            print("No chemistry was run. Use --smoke --out NEW_DIR on a compute node to test runtime.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
