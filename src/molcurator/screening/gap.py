"""Frozen empirical GFN2-xTB -> ORCA B3LYP/def2-SVP gap calibration.

Use only for HOMO-LUMO *orbital* gaps on neutral closed-shell molecules with
compatible xTB-optimized geometries. Not S1, fluorescence, or S1-T1 gaps.

This module deliberately does NOT modify Prediction.value or the tool contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from molcurator.schemas import Prediction, PropertyTarget, Status


@dataclass(frozen=True)
class GapCalibration:
    name: str = "linear_24"
    slope: float = 0.8270780546046135
    intercept_ev: float = 2.9901896256531098
    qm_method: str = "dft:B3LYP/def2-SVP"

    def __post_init__(self):
        if not all(isfinite(v) for v in (self.slope, self.intercept_ev)):
            raise ValueError("Calibration coefficients must be finite")

    @classmethod
    def constant_offset(cls) -> "GapCalibration":
        return cls(name="constant_offset_24", slope=1.0,
                   intercept_ev=2.2617441034023127)

    def predict(self, xtb_gap_ev: float) -> float:
        value = float(xtb_gap_ev)
        if not isfinite(value) or value < 0:
            raise ValueError("xTB gap must be finite and nonnegative")
        corrected = self.slope * value + self.intercept_ev
        if not isfinite(corrected):
            raise ValueError("calibrated gap is nonfinite")
        return corrected


def screening_decision(prediction: Prediction, target: PropertyTarget,
                       calibration: GapCalibration, margin_ev: float = 0.75) -> dict:
    """Evaluate one raw prediction; preserve its unmodified value and status.

    `selected` means provisional eligibility for QM/ranking, NOT a statistically
    validated hard rejection rule. Failed predictions stay failed.
    """
    if target.name != "homo_lumo_gap" or target.units != "eV":
        raise ValueError("Calibration only supports homo_lumo_gap (eV)")
    if not isfinite(margin_ev) or margin_ev < 0:
        raise ValueError("margin_ev must be finite and nonnegative")
    record = {
        "candidate_id": prediction.candidate_id,
        "status": prediction.status.value,
        "raw_xtb_gap_ev": prediction.value,
        "calibrated_gap_ev": None,
        "calibration": calibration.name,
        "calibration_qm_method": calibration.qm_method,
        "margin_ev": margin_ev,
        "selected": False,
        "distance_to_target_ev": None,
        "xyz_path": str(prediction.xyz_path) if prediction.xyz_path else None,
        "error": prediction.error,
    }
    if prediction.status != Status.ok or prediction.value is None:
        return record
    value = calibration.predict(prediction.value)
    low = target.min if target.min is not None else float("-inf")
    high = target.max if target.max is not None else float("inf")
    record["calibrated_gap_ev"] = value
    distance = max(low - value, 0.0, value - high)
    record["distance_to_target_ev"] = distance
    record["selected"] = distance <= margin_ev
    return record


def ranked_predictions(predictions: Iterable[Prediction], target: PropertyTarget,
                       calibration: GapCalibration | None = None,
                       margin_ev: float = 0.75) -> list[dict]:
    """Stable rank of predictions; failures retained last, original IDs intact."""
    calibration = calibration or GapCalibration()
    rows = [screening_decision(p, target, calibration, margin_ev)
            for p in predictions]
    # Stable sort retains original order for equal distances, including failures.
    return sorted(rows, key=lambda r: (
        r["status"] != "ok",
        float("inf") if r["distance_to_target_ev"] is None else r["distance_to_target_ev"]
    ))
