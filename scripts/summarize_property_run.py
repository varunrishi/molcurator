"""Read calculation attempts, cache hits and runtimes for a run directory."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subprojects/property_validation_v1/src"))
from molcurator_property_validation.chem.summary import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.run_dir.is_dir():
        parser.error("run directory does not exist")
    report = summarize(args.run_dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key in ("events", "cache_hits", "electronic_calls_attempted", "by_backend",
                    "failed_events", "running_or_interrupted", "runtime_s", "record_errors"):
            print(f"{key}: {report[key]}")
    return 1 if report["record_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
