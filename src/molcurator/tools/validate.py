# VALIDATE: confirm screened candidates with higher-accuracy quantum chemistry.
#
# Backends: ORCA (binary from ORCA_BIN, else `orca` on PATH)
#           PySCF fallback remains unimplemented.
#   - DFT for HOMO / LUMO / gap
#   - TADF S1/T1 calculations remain unimplemented.
# Input geometries come from PREDICT (xTB-optimised).
# Output: one QMResult (schemas.py) per molecule, with method naming the level of theory.
from molcurator.schemas import Prediction, PropertyTarget, QMResult, QMSettings


def validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]:
    """QM value of the target property for each selected molecule (contract: Phase 2 plan, R2.2).

    Starts from each item's xTB geometry (xyz_path). Returns exactly one QMResult per item, in
    the same order, with `method` naming the level of theory (e.g. "dft:B3LYP/def2-SVP"). A
    failed calculation is returned with status "failed" and an error, never dropped. The agent
    only passes the QM batch, already trimmed to the remaining QM budget (R4.2).
    """
    from molcurator_property_validation.tools.validate import validate as validate_orca

    return validate_orca(items, target, qm)
