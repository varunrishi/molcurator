"""Evaluate an agreed agent-v1 or original provisional JSONL trace offline."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--format", choices=("auto", "agent-v1", "provisional-v1"), default="auto")
    parser.add_argument("--max-rounds", type=int)
    parser.add_argument("--max-qm-calls", type=int)
    parser.add_argument("--max-wall-time", type=float)
    parser.add_argument("--target-dataset-size", type=int)
    parser.add_argument("--qm-disabled", action="store_const", const=False, default=None)
    parser.add_argument("--ml-enabled", action="store_const", const=True, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    created_output = False
    try:
        if args.trace.resolve() == args.out.resolve():
            raise ValueError("output must not overwrite input trace")
        events, source = load_trace(args.trace)
        policy = dict(max_rounds=args.max_rounds,
            max_qm_calls=args.max_qm_calls, max_wall_time=args.max_wall_time,
            target_dataset_size=args.target_dataset_size)
        report = evaluate_trajectory(events, budgets={key: value for key, value in policy.items() if value is not None} or None,
            qm_enabled=args.qm_disabled, ml_enabled=args.ml_enabled, source=source, trace_format=args.format)
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        with args.out.open("x", encoding="utf-8") as handle:
            created_output = True
            handle.write(serialized)
    except (OSError, ValueError, TypeError) as exc:
        if created_output:
            args.out.unlink(missing_ok=True)
        parser.error(str(exc))
    print(json.dumps(dict(overall=report["overall"], checks=report["checks"],
        capabilities=report["capabilities"], summary=report["summary"]), indent=2))
    return 1 if report["overall"] == "fail" else 3 if report["overall"] == "not_assessable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
