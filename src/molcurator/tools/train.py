# TRAIN: fit an ML model on molecules labelled by xTB, and score candidates with it (Phase 2, R10).
#
# Each round the agent runs xTB on a random sample of candidates, calls train() on every molecule
# labelled so far, then ml_predict() on the candidates xTB did not run on; SCREEN uses those ML
# estimates. The model itself (ChemProp, fingerprint ridge, ...) is the tool owner's choice.
from pathlib import Path

from molcurator.schemas import Candidate, Prediction, PropertyTarget, TrainingExample, TrainResult


def train(examples: list[TrainingExample], target: PropertyTarget, model_dir: Path) -> TrainResult:
    """Fit a model predicting the target property from SMILES and save it under model_dir (R10.2, R10.3).

    Called every round with ALL xTB-labelled molecules so far: train from this full list, don't
    add to an earlier model. Raise if training is impossible (there is no partial result).
    """
    raise NotImplementedError("train() is built by the tool work; use FakeTools in tests")


def ml_predict(candidates: list[Candidate], target: PropertyTarget, model: TrainResult) -> list[Prediction]:
    """ML estimate of the target property for each candidate, using the model train() saved (R10.4).

    Exactly one Prediction per candidate, in the same order; a molecule the model cannot handle is
    returned with status "failed" and an error, never dropped. No geometry: xyz_path stays None.
    """
    raise NotImplementedError("ml_predict() is built by the tool work; use FakeTools in tests")
