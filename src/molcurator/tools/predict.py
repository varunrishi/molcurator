# PREDICT: cheap physics-based property estimate for a candidate.
#
# Pipeline: SMILES -> MMFF94 conformer ensemble -> lowest converged minimum (chem/geometry.py)
#           -> single point of the target property at that geometry (chem/backends.py)
# Method: GFN2-xTB through tblite (in-process, seconds) when xTB can give the target; else
# B97-3c through ORCA, e.g. TD-DFT for s1_t1_gap, which xTB cannot give. A run config's
# predict.method / predict.basis (or the batch command's --predict-method / --predict-basis)
# replace the default; check_predict_level rejects impossible choices before a run starts.
# Never upgraded silently: a method that cannot give the target fails the molecule.
# Output: one Prediction (schemas.py) per candidate, with the selected geometry at
# xyz_dir/<id>.xyz (its comment line carries charge and multiplicity for VALIDATE), and
# per-molecule records in xyz_dir/calculations/<id>/ (geometry_report.json, predict.json).
from collections.abc import Callable
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
from molcurator.chem.orca import DEFAULT_BASIS
from molcurator.chem.settings import load_settings
from molcurator.fileio import atomic_json, safe_id
from molcurator.schemas import Candidate, Prediction, PropertyTarget, Status

XTB_METHOD = "gfn2-xtb"
DFT_METHOD = "B97-3c"  # cheapest composite DFT with sound TD-DFT; used when xTB cannot give the target


def default_method(target: PropertyTarget) -> str:
    return XTB_METHOD if target.name in xtb.PROPERTIES else DFT_METHOD


def _own_basis(method: str) -> bool:
    """True for methods that bring their own basis: xTB and composite "-3c" DFT."""
    return xtb.is_xtb(method) or method.split()[0].lower().endswith("-3c")


def _level(method: str, basis: str | None) -> tuple[str, str | None]:
    """Comparable (method, basis); basis None where the method fixes its own."""
    return " ".join(method.lower().split()), None if _own_basis(method) else (basis or DEFAULT_BASIS).lower()


def check_predict_level(target_name: str, method: str | None, basis: str | None,
                        qm_method: str | None = None, qm_basis: str | None = None) -> None:
    """Raise ValueError, naming the fix, for a PREDICT level that cannot work: xTB for a target
    only DFT/TD-DFT gives, a basis set for a method with its own, or the same level as
    VALIDATE (qm_method / qm_basis, when QM is on), which would check PREDICT against itself."""
    if method is None:
        if basis:
            raise ValueError("predict.basis needs predict.method: the default method sets its own basis")
        method = DFT_METHOD if target_name not in xtb.PROPERTIES else XTB_METHOD
    if xtb.is_xtb(method) and target_name not in xtb.PROPERTIES:
        raise ValueError(f"predict.method {method!r} is an xTB method, which cannot give {target_name}: "
                         f"use a DFT method (default {DFT_METHOD}, a TD-DFT-capable composite method)")
    if basis and _own_basis(method):
        raise ValueError(f"predict.basis {basis!r} would be ignored: {method} brings its own basis set; "
                         "remove predict.basis or choose a method without one (e.g. PBE0)")
    if qm_method and _level(method, basis) == _level(qm_method, qm_basis):
        raise ValueError(f"PREDICT and VALIDATE both use {method}" + (f"/{basis}" if basis else "") +
                         "; VALIDATE must use a higher level of theory than PREDICT to check it")


def _predict_one(candidate: Candidate, target: PropertyTarget, xyz_dir: Path, method: str,
                 basis: str | None) -> Prediction:
    cid = safe_id(candidate.id)
    folder = (xyz_dir / "calculations" / cid).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    output = (xyz_dir / f"{cid}.xyz").resolve()
    output.unlink(missing_ok=True)  # a repeat attempt must not leave a stale geometry behind
    settings = load_settings()
    record = {"candidate_id": candidate.id, "smiles": candidate.smiles, "stage": "predict", "property": target.name,
              "requested_method": method, "requested_basis": basis, "status": "failed"}
    try:
        xyz, report = lowest_ff_conformer(candidate.smiles, settings)
        charge, multiplicity = report["formal_charge"], multiplicity_from_report(report)
        atomic_json(folder / "geometry_report.json", {**report, "candidate_id": candidate.id, "smiles": candidate.smiles})
        geometry = folder / "geometry.xyz"
        geometry.write_text(with_comment(xyz, charge_multiplicity_comment(charge, multiplicity)))
        elements, coordinates = read_xyz(geometry)
        result = calculate_property(elements, coordinates, target.name, method, basis, charge, multiplicity,
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
    The method is default_method(target); predict_at() makes a predict() for another level.
    """
    return predict_with_method(candidates, target, xyz_dir, None)


def predict_at(method: str | None, basis: str | None = None) -> Callable[..., list[Prediction]]:
    """predict() at a configured level (a run config's predict.method / predict.basis), with
    predict()'s exact signature, so it keeps the agent's tool contract."""
    if method is None and basis is None:
        return predict

    def predict_configured(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]:
        return predict_with_method(candidates, target, xyz_dir, method, basis)

    return predict_configured


def predict_with_method(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path,
                        method: str | None, basis: str | None = None) -> list[Prediction]:
    """predict() at an explicit level (method None: default_method(target)); used by
    predict_at and by the batch command's --predict-method / --predict-basis."""
    method = method or default_method(target)
    results = []
    for candidate in candidates:
        try:
            results.append(_predict_one(candidate, target, xyz_dir, method, basis))
        except Exception as exc:  # noqa: BLE001 - an unsafe id or unwritable folder: still one failed result per candidate
            results.append(Prediction(candidate_id=candidate.id, status=Status.failed,
                                      error=f"{type(exc).__name__}: {exc}"))
    return results
