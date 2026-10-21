"""Post-prediction calibration and candidate ranking; never modifies QC tool outputs."""
from .gap import GapCalibration, ranked_predictions, screening_decision
__all__ = ["GapCalibration", "ranked_predictions", "screening_decision"]
