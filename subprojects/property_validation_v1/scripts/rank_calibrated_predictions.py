"""Rank exported Prediction records without altering the MolCurator tool contract.

Example: uv run python scripts/rank_calibrated_predictions.py --input predictions.json --output ranked.csv
`predictions.json` may be a list or object with `predictions` list.
"""
import argparse
import csv
import json
from pathlib import Path

from molcurator.schemas import Prediction, PropertyTarget
from molcurator_property_validation.screening import GapCalibration, ranked_predictions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--min", type=float, default=3.0)
    ap.add_argument("--max", type=float, default=3.5)
    ap.add_argument("--margin", type=float, default=0.75)
    ap.add_argument("--model", choices=["linear", "constant_offset"], default="linear")
    args = ap.parse_args()
    content = json.loads(args.input.read_text())
    records = content.get("predictions", []) if isinstance(content, dict) else content
    predictions = [Prediction.model_validate(p) for p in records]
    target = PropertyTarget(name="homo_lumo_gap", min=args.min, max=args.max)
    model = GapCalibration() if args.model == "linear" else GapCalibration.constant_offset()
    rows = ranked_predictions(predictions, target, model, args.margin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["candidate_id", "status", "raw_xtb_gap_ev", "calibrated_gap_ev",
                  "calibration", "calibration_qm_method", "margin_ev", "selected",
                  "distance_to_target_ev", "xyz_path", "error"]
    with args.output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Ranked {len(rows)} predictions; {sum(r['selected'] for r in rows)} within provisional margin; wrote {args.output}")


if __name__ == "__main__":
    main()
