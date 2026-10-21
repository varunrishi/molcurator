"""Create py3Dmol molecule viewers from a saved smoke run or prediction collection."""
import argparse
import json
from pathlib import Path

from molcurator.visualization import export_prediction_gallery


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True, help="JSON list or object with 'predictions' list")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-viewers", type=int, default=30)
    args = ap.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    predictions = data["predictions"] if isinstance(data, dict) else data
    if not isinstance(predictions, list):
        ap.error("input must be a list or object containing a predictions list")
    print(json.dumps(export_prediction_gallery(predictions, args.out, max_molecules=args.max_viewers), indent=2)[:1200])


if __name__ == "__main__":
    main()
