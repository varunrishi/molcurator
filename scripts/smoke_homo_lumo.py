"""Run one real xTB -> ORCA adapter check, independent of the unfinished agent CLI."""
import argparse
import json
import sys
from pathlib import Path

# Permit direct execution with an existing cluster Python containing RDKit/Pydantic.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate


def smoke(smiles: str, molecule_id: str, out: Path, qm: QMSettings) -> int:
    """Validate one molecule regardless of gap; this checks execution, not target hits."""
    out = out.resolve()
    # Avoid overwriting a prior calculation or confusing an old result with a new one.
    out.mkdir(parents=True, exist_ok=False)
    target = PropertyTarget(name="homo_lumo_gap", min=0, units="eV")
    candidate = Candidate(id=molecule_id, smiles=smiles, parent_smiles=smiles,
                          round=1, generator="manual_smoke")
    predictions = predict([candidate], target, out / "xyz")
    result = dict(candidate=candidate.model_dump(mode="json"),
                  target=target.model_dump(mode="json"), qm=qm.model_dump(mode="json"),
                  predictions=[p.model_dump(mode="json") for p in predictions],
                  qm_results=[])
    report = out / "results.json"
    report.write_text(json.dumps(result, indent=2))
    if predictions[0].status is Status.ok:
        results = validate(predictions, target, qm)
        result["qm_results"] = [r.model_dump(mode="json") for r in results]
        success = results[0].status is Status.ok
    else:
        success = False
    result["status"] = "ok" if success else "failed"
    report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smiles", default="CCO")
    parser.add_argument("--id", default="ethanol")
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    parser.add_argument("--functional", default="B3LYP")
    parser.add_argument("--basis", default="def2-SVP")
    args = parser.parse_args()
    return smoke(args.smiles, args.id, args.out,
                 QMSettings(backend="orca", functional=args.functional, basis=args.basis))


if __name__ == "__main__":
    raise SystemExit(main())
