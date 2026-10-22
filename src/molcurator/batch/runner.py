"""Checkpointed batch execution, independent of command-line parsing.

Each molecule is predicted, then (with --orca) validated if its predicted value lies in the
selection window and the per-invocation limit is not reached. results.json is rewritten
after every step, so an interrupted run resumes where it stopped (--resume).
"""
import hashlib
import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

from molcurator.batch.inputs import read_candidates
from molcurator.batch.runtime import check_allocation, run_lock
from molcurator.chem.properties import SCALAR_PROPERTIES
from molcurator.chem.settings import active_settings, load_settings
from molcurator.fileio import atomic_json, native_path
from molcurator.schemas import PropertyTarget, QMSettings, Status

SCHEMA_VERSION = 2


def _target(args) -> PropertyTarget:
    """The target the tools receive. They read only its name; the window is applied here."""
    if args.property not in SCALAR_PROPERTIES:
        raise ValueError(f"--property must be one of {', '.join(SCALAR_PROPERTIES)}")
    if any(v is not None and not math.isfinite(v) for v in (args.min, args.max)):
        raise ValueError("--min and --max must be finite")
    if args.min is None and args.max is None:  # no window: every successful prediction is selected
        return PropertyTarget(name=args.property, min=-math.inf, units=args.units)
    return PropertyTarget(name=args.property, min=args.min, max=args.max, units=args.units)


def run_batch(args, *, predict_fn, validate_fn) -> int:
    from molcurator.batch.reporting import generate_report, require_plotting
    if args.plots:
        require_plotting()
    candidates = read_candidates(args.input, args.format)
    settings = load_settings()
    target = _target(args)
    qm = QMSettings(backend="orca", functional=args.functional, basis=args.basis)
    if args.orca_limit is not None and not args.orca:
        raise ValueError("--orca-limit requires --orca")
    if args.orca_limit is not None and args.orca_limit < 0:
        raise ValueError("--orca-limit must be nonnegative")
    from molcurator.chem.backends import backend_for
    from molcurator.tools.predict import default_method
    predict_method = args.predict_method or default_method(target)
    check_allocation(settings, args.orca or backend_for(predict_method) == "orca")
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
            if old.get("schema_version") != SCHEMA_VERSION or old.get("input_fingerprint") != fingerprint:
                raise ValueError("resume input or results format differs; use a new output directory")
            history = output / "history"
            history.mkdir(exist_ok=True)
            atomic_json(history / (old["invocation_id"] + ".json"), old)
        window = {"min": args.min, "max": args.max}
        state = {"schema_version": SCHEMA_VERSION, "invocation_id": uuid.uuid4().hex,
                 "input_path": str(Path(args.input).resolve()), "input_fingerprint": fingerprint,
                 "started_at": datetime.now(UTC).isoformat(), "run_status": "running",
                 "settings": settings.model_dump(), "target": {"name": target.name, "units": target.units, **window},
                 "predict_method": predict_method, "qm": qm.model_dump(mode="json") if args.orca else None,
                 "orca_limit": args.orca_limit,
                 "rows": [{"candidate": c, "prediction": None, "qm_result": None,
                           "qm_selection": "pending" if args.orca else "not_requested"} for c in dataset]}

        def checkpoint():
            atomic_json(output / "results.json", state)

        checkpoint()
        selected = 0
        exit_code = 0
        token = active_settings.set(settings)  # one frozen copy for the whole invocation
        try:
            for candidate, row in zip(candidates, state["rows"], strict=True):
                prediction = predict_fn([candidate], target, output / "xyz", predict_method)[0]
                row["prediction"] = prediction.model_dump(mode="json")
                checkpoint()
                if prediction.status is Status.failed:
                    exit_code = 1
                    if args.orca:
                        row["qm_selection"] = "prediction_failed"
                elif args.orca:
                    in_window = ((args.min is None or prediction.value >= args.min)
                                 and (args.max is None or prediction.value <= args.max))
                    within_limit = args.orca_limit is None or selected < args.orca_limit
                    if in_window and within_limit:
                        selected += 1
                        row["qm_selection"] = "selected"
                        checkpoint()
                        result = validate_fn([prediction], target, qm)[0]
                        row["qm_result"] = result.model_dump(mode="json")
                        if result.status is Status.failed:
                            exit_code = 1
                    else:
                        row["qm_selection"] = "outside_window" if not in_window else "limit_reached"
                checkpoint()
            state["run_status"] = "completed_with_failures" if exit_code else "completed"
        except KeyboardInterrupt:
            state["run_status"] = "interrupted"
            exit_code = 130
        except Exception as exc:  # noqa: BLE001 - recorded in results.json and the report
            state.update(run_status="error", error=f"{type(exc).__name__}: {exc}")
            exit_code = 1
        finally:
            active_settings.reset(token)
            state["finished_at"] = datetime.now(UTC).isoformat()
            checkpoint()
            generate_report(output, plots=args.plots)
        print(f"{state['run_status']}: {output / 'report.md'}")
        return exit_code
