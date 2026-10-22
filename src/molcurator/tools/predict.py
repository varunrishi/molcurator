# PREDICT: cheap physics-based property estimate for a candidate.
#
# Pipeline: SMILES -> MMFF94 conformer ensemble -> lowest converged minimum (chem/geometry.py)
#           -> single point of the target property at that geometry (chem/backends.py)
# Method: GFN2-xTB through tblite (in-process, seconds) when xTB can give the target; else
# B97-3c through ORCA, e.g. TD-DFT for s1_t1_gap, which xTB cannot give. Never upgraded
# silently: a method that cannot give the target fails the molecule.
# Output: one Prediction (schemas.py) per candidate, with the selected geometry at
# xyz_dir/<id>.xyz (its comment line carries charge and multiplicity for VALIDATE), and
# per-molecule records in xyz_dir/calculations/<id>/ (geometry_report.json, predict.json).
from pathlib import Path

from molcurator.chem import xtb
from molcurator.chem.backends import calculate_property, method_label
from molcurator.chem.geometry import (
    GeometryError,
    charge_multiplicity_comment,
    lowest_ff_conformer,
    multiplicity_from_report,
    read_xyz,
    with_comment,
)
from molcurator.chem.settings import load_settings
from molcurator.fileio import atomic_json, safe_id
from molcurator.schemas import Candidate, Prediction, PropertyTarget, Status

XTB_METHOD = "gfn2-xtb"
DFT_METHOD = "B97-3c"  # cheapest composite DFT with sound TD-DFT; used when xTB cannot give the target


def default_method(target: PropertyTarget) -> str:
    return XTB_METHOD if target.name in xtb.PROPERTIES else DFT_METHOD


def _predict_one(candidate: Candidate, target: PropertyTarget, xyz_dir: Path, method: str) -> Prediction:
    cid = safe_id(candidate.id)
    folder = (xyz_dir / "calculations" / cid).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    output = (xyz_dir / f"{cid}.xyz").resolve()
    output.unlink(missing_ok=True)  # a repeat attempt must not leave a stale geometry behind
    settings = load_settings()
    record = {"candidate_id": candidate.id, "smiles": candidate.smiles, "stage": "predict", "property": target.name,
              "requested_method": method, "status": "failed"}
    try:
        xyz, report = lowest_ff_conformer(candidate.smiles, settings)
        charge, multiplicity = report["formal_charge"], multiplicity_from_report(report)
        atomic_json(folder / "geometry_report.json", {**report, "candidate_id": candidate.id, "smiles": candidate.smiles})
        geometry = folder / "geometry.xyz"
        geometry.write_text(with_comment(xyz, charge_multiplicity_comment(charge, multiplicity)))
        elements, coordinates = read_xyz(geometry)
        result = calculate_property(elements, coordinates, target.name, method, None, charge, multiplicity,
                                    folder / "predict", settings)
        record.update(result, stage="predict", status="ok" if result["success"] else "failed")
        if not result["success"]:
            return Prediction(candidate_id=candidate.id, status=Status.failed, error=result["error"])
        if not isinstance(result["value"], (int, float)):
            raise TypeError(f"{target.name} is not a single number, so it cannot be a target property")
        output.write_text(geometry.read_text())
        record.update(method_label=method_label(result), xyz_path=str(output))
        return Prediction(candidate_id=candidate.id, status=Status.ok, value=result["value"], xyz_path=output)
    except GeometryError as exc:
        record.update(failure_stage=exc.stage, failure_code=exc.code, error=f"GeometryError: {exc}")
        return Prediction(candidate_id=candidate.id, status=Status.failed, error=record["error"])
    except Exception as exc:  # noqa: BLE001 - recorded as a failed molecule, never raised
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        return Prediction(candidate_id=candidate.id, status=Status.failed, error=record["error"])
    finally:
        atomic_json(folder / "predict.json", record)


def predict(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]:
    """Cheap estimate of the target property for each candidate (contract: Phase 2 plan, R2.2).

    Returns exactly one Prediction per candidate, in the same order. A molecule that fails
    (geometry, calculation) is returned with status "failed" and an error, never dropped.
    Every "ok" result has a value and the selected MMFF94 geometry written to xyz_dir/<id>.xyz.
    The method is default_method(target).
    """
    return predict_with_method(candidates, target, xyz_dir, None)


def predict_with_method(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path,
                        method: str | None) -> list[Prediction]:
    """predict() with an explicit method (None: default_method(target)); the batch command's
    --predict-method. Kept apart so predict() keeps the agent's tool contract."""
    method = method or default_method(target)
    results = []
    for candidate in candidates:
        try:
            results.append(_predict_one(candidate, target, xyz_dir, method))
        except Exception as exc:  # noqa: BLE001 - an unsafe id or unwritable folder: still one failed result per candidate
            results.append(Prediction(candidate_id=candidate.id, status=Status.failed,
                                      error=f"{type(exc).__name__}: {exc}"))
    return results
