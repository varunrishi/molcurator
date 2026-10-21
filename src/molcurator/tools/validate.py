# VALIDATE: confirm screened candidates with higher-accuracy quantum chemistry.
#
# Backends: ORCA (default, via its Python interface OPI; binary from ORCA_BIN, else `orca` on PATH)
#           or PySCF (fallback, installed with the package).
#   - DFT for HOMO / LUMO / gap
#   - TD-DFT for S1 and T1 energies (S1-T1 gap for the TADF use case)
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
    raise NotImplementedError("validate() is built in Phase 1 (tools); use FakeToolset in tests")
