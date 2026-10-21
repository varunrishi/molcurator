"""Property-prediction CLI for generated molecules and optional model training."""
import argparse
import csv
import json
from pathlib import Path

from molcurator.schemas import Candidate, QMSettings, Status
from .predictor import PredictorSettings, predict_properties


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict", help="predict properties for generated molecule JSON")
    predict.add_argument("--input", type=Path, required=True)
    predict.add_argument("--output", type=Path, required=True, help="new output directory")
    predict.add_argument("--backend", choices=["xtb", "orca", "ml"], default="xtb")
    predict.add_argument("--properties", nargs="+", default=["homo_lumo_gap"])
    predict.add_argument("--functional", default="B3LYP")
    predict.add_argument("--basis", default="def2-SVP")
    predict.add_argument("--geometry", choices=["xtb", "force_field"], default="xtb")
    predict.add_argument("--model", type=Path)
    train = commands.add_parser("train-ml", help="fit a portable model from your own labelled CSV")
    train.add_argument("--input", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--properties", nargs="+", default=["homo_lumo_gap"])
    train.add_argument("--reference-method", required=True)
    train.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()
    if args.command == "train-ml":
        from .ml import train_fingerprint_model
        with args.input.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        if any(r.get("method", args.reference_method) != args.reference_method for r in rows):
            parser.error("label methods must match --reference-method")
        model = train_fingerprint_model([r["smiles"] for r in rows],
                    {p: [float(r[p]) for r in rows] for p in args.properties},
                    reference_method=args.reference_method, alpha=args.alpha)
        model.save(args.output)
        print(f"Saved model fitted on {len(rows)} molecules. Independent validation is still required.")
        return 0
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    rows = data["candidates"] if isinstance(data, dict) else data
    candidates = [Candidate(id=r["id"], smiles=r["smiles"], parent_smiles=r.get("parent_smiles", r["smiles"]),
                  round=r.get("round", 1), generator=r.get("generator", "external")) for r in rows]
    settings = PredictorSettings(backend=args.backend, properties=args.properties,
               qm=QMSettings(backend="orca", functional=args.functional, basis=args.basis),
               geometry=args.geometry, model_path=args.model)
    results = predict_properties(candidates, settings, args.output)
    failed = sum(r.status is Status.failed for r in results)
    print(f"Predicted {len(results)} molecules; {failed} failed/partial. Results: {args.output / 'predictions.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
