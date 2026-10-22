# VALIDATE: confirm screened candidates with higher-accuracy quantum chemistry.
#
# Backend: ORCA through OPI (chem/orca.py); the binary is ORCA_BIN, else `orca` on PATH.
#          PySCF remains unimplemented.
# Any property chem/orca.py knows can be the target: DFT for HOMO/LUMO gaps, TD-DFT for the
# S1-T1 gap, and so on, at qm.functional / qm.basis with TightSCF.
# Input geometries come from PREDICT (MMFF94-optimised); their XYZ comment line carries
# charge and multiplicity. Records go to <xyz dir>/calculations/<id>/validate.json.
# Output: one QMResult (schemas.py) per molecule, with method naming the level of theory.
from molcurator.chem.backends import calculate_property, method_label
from molcurator.chem.geometry import read_charge_multiplicity, read_xyz
from molcurator.chem.settings import load_settings
from molcurator.fileio import atomic_json, safe_id
from molcurator.schemas import Prediction, PropertyTarget, QMResult, QMSettings, Status


def _validate_one(item: Prediction, target: PropertyTarget, qm: QMSettings) -> QMResult:
    method = f"dft:{qm.functional}/{qm.basis}"
    if qm.backend != "orca":
        raise ValueError(f"QM backend {qm.backend!r} is not implemented; use orca")
    if item.status is not Status.ok or item.xyz_path is None:
        raise ValueError("a successful prediction with a geometry is required")
    cid = safe_id(item.candidate_id)
    geometry = item.xyz_path.resolve()
    folder = geometry.parent / "calculations" / cid
    folder.mkdir(parents=True, exist_ok=True)
    elements, coordinates = read_xyz(geometry)
    charge, multiplicity = read_charge_multiplicity(geometry)
    result = calculate_property(elements, coordinates, target.name, qm.functional, qm.basis, charge, multiplicity,
                                folder / "validate", load_settings(), extra_keywords=["TightSCF"])
    atomic_json(folder / "validate.json", {**result, "candidate_id": item.candidate_id, "stage": "validate",
                                           "status": "ok" if result["success"] else "failed",
                                           "method_label": method_label(result) if result["success"] else method})
    if not result["success"]:
        return QMResult(candidate_id=item.candidate_id, method=method, status=Status.failed, error=result["error"])
    if not isinstance(result["value"], (int, float)):
        raise TypeError(f"{target.name} is not a single number, so it cannot be a target property")
    return QMResult(candidate_id=item.candidate_id, method=method_label(result), status=Status.ok,
                    value=result["value"])


def validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]:
    """QM value of the target property for each selected molecule (contract: Phase 2 plan, R2.2).

    Starts from each item's selected MMFF94 geometry (xyz_path). Returns exactly one QMResult per item, in
    the same order, with `method` naming the level of theory (e.g. "dft:B3LYP/def2-SVP"). A
    failed calculation is returned with status "failed" and an error, never dropped. The agent
    only passes the QM batch, already trimmed to the remaining QM budget (R4.2).
    """
    results = []
    for item in items:
        try:
            results.append(_validate_one(item, target, qm))
        except Exception as exc:  # noqa: BLE001 - one failed result per molecule, never raised
            results.append(QMResult(candidate_id=item.candidate_id, method=f"dft:{qm.functional}/{qm.basis}",
                                    status=Status.failed, error=f"{type(exc).__name__}: {exc}"))
    return results
