# PREDICT: cheap physics-based property estimate for a candidate.
#
# Pipeline: SMILES -> RDKit 3D embedding -> xTB (GFN2) geometry optimisation
#           -> property extraction (e.g. HOMO, LUMO, HOMO-LUMO gap)
# Calls the external `xtb` binary: XTB_BIN from the environment / .env (written by
# scripts/setup.sh), otherwise `xtb` on PATH.
# Output: one Prediction (schemas.py) per candidate, with the optimised XYZ geometry path.
from pathlib import Path

from molcurator.schemas import Candidate, Prediction, PropertyTarget


def predict(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]:
    """xTB estimate of the target property for each candidate (contract: Phase 2 plan, R2.2).

    Returns exactly one Prediction per candidate, in the same order. A molecule that fails
    (embedding, xTB convergence) is returned with status "failed" and an error, never dropped.
    Every "ok" result has a value and the optimised geometry written to xyz_dir/<id>.xyz.
    """
    from molcurator_property_validation.tools.predict import predict as predict_xtb

    return predict_xtb(candidates, target, xyz_dir)
