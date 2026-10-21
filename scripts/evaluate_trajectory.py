"""Evaluate a saved provisional-v1 agent JSONL trace without executing the agent."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--max-rounds", type=int, required=True)
    parser.add_argument("--max-qm-calls", type=int, required=True)
    parser.add_argument("--max-wall-time", type=float, required=True)
    parser.add_argument("--target-dataset-size", type=int, required=True)
    parser.add_argument("--qm-disabled", action="store_true")
    parser.add_argument("--ml-enabled", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    created_output = False
    try:
        if args.trace.resolve() == args.out.resolve():
            raise ValueError("output must not overwrite input trace")
        events, source = load_trace(args.trace)
        report = evaluate_trajectory(events, budgets=dict(max_rounds=args.max_rounds,
            max_qm_calls=args.max_qm_calls, max_wall_time=args.max_wall_time,
            target_dataset_size=args.target_dataset_size), qm_enabled=not args.qm_disabled,
            ml_enabled=args.ml_enabled, source=source)
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        with args.out.open("x", encoding="utf-8") as handle:
            created_output = True
            handle.write(serialized)
    except (OSError, ValueError, TypeError) as exc:
        if created_output:
            args.out.unlink(missing_ok=True)
        parser.error(str(exc))
    print(json.dumps(dict(overall=report["overall"], checks=report["checks"], summary=report["summary"]), indent=2))
    return 1 if report["overall"] == "fail" else 3 if report["overall"] == "not_assessable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
