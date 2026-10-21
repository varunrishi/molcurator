"""Evaluate saved collaborator CSV or curated JSONL without running chemistry."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from molcurator.evaluation import evaluate_dataset, load_records, write_reports
from molcurator.schemas import PropertyTarget


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--format", choices=("csv", "jsonl"), required=True)
    parser.add_argument("--property", default="homo_lumo_gap")
    parser.add_argument("--units", default="eV")
    parser.add_argument("--min", type=float)
    parser.add_argument("--max", type=float)
    parser.add_argument("--qm-method", required=True)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--qm-results", type=Path, help="Serialized QMResult objects, one per JSONL line")
    parser.add_argument("--artifact-root", type=Path, help="Optional base for checking XYZ file existence")
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--csv-out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        inputs = {args.input.resolve()}
        if args.qm_results:
            inputs.add(args.qm_results.resolve())
        if args.json_out.resolve() in inputs or args.csv_out.resolve() in inputs:
            raise ValueError("report paths must not overwrite inputs")
        records, source = load_records(args.input, args.format)
        results, qm_source = load_records(args.qm_results, "jsonl") if args.qm_results else (None, None)
        target = PropertyTarget(name=args.property, min=args.min, max=args.max, units=args.units)
        report = evaluate_dataset(records, target=target, qm_method=args.qm_method,
                                  profile=args.format, seeds=args.seed, qm_results=results,
                                  source=source, artifact_root=args.artifact_root)
        report["metadata"]["qm_results_source"] = qm_source
        write_reports(report, args.json_out, args.csv_out)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report["summary"], indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
