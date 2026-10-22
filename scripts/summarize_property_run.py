"""Count the recorded calculations, failures and runtime of a run's xyz/ directory (an agent
run's data/runs/<id>/xyz or a batch run's <out>/xyz)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from molcurator.batch.reporting import summarize


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xyz_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.xyz_dir.is_dir():
        parser.error("directory does not exist")
    report = summarize(args.xyz_dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key in ("calculations", "by_backend", "failed", "runtime_s", "record_errors"):
            print(f"{key}: {report[key]}")
    return 1 if report["record_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
