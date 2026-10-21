import math
import pytest
from molcurator.schemas import Prediction, PropertyTarget, Status
from molcurator_property_validation.screening import GapCalibration, screening_decision, ranked_predictions

TARGET = PropertyTarget(name="homo_lumo_gap", min=3.0, max=3.5)


def test_calibration_frozen_parameters():
    assert GapCalibration().predict(4.0) == pytest.approx(0.8270780546046135 * 4 + 2.9901896256531098)
    assert GapCalibration.constant_offset().predict(4) == pytest.approx(6.261744103402313)


def test_does_not_mutate_prediction():
    p = Prediction(candidate_id="a", status=Status.ok, value=0.4)
    old = p.model_dump()
    row = screening_decision(p, TARGET, GapCalibration(), 0.75)
    assert p.model_dump() == old
    assert row["raw_xtb_gap_ev"] == 0.4
    assert row["selected"]


def test_failures_retained_and_stably_ranked():
    predictions = [Prediction(candidate_id="failed", status=Status.failed, error="xtb failed"),
                   Prediction(candidate_id="one", status=Status.ok, value=1.0),
                   Prediction(candidate_id="two", status=Status.ok, value=1.0)]
    rows = ranked_predictions(predictions, TARGET)
    assert [r["candidate_id"] for r in rows] == ["one", "two", "failed"]
    assert rows[-1]["error"] == "xtb failed"


def test_reject_unsupported_target_and_bad_margin():
    p = Prediction(candidate_id="a", status=Status.ok, value=3.0)
    with pytest.raises(ValueError):
        screening_decision(p, PropertyTarget(name="s1_t1_gap", max=0.2), GapCalibration())
    with pytest.raises(ValueError):
        screening_decision(p, TARGET, GapCalibration(), math.nan)


def test_one_sided_target():
    p = Prediction(candidate_id="a", status=Status.ok, value=0.0)
    row = screening_decision(p, PropertyTarget(name="homo_lumo_gap", max=3.5), GapCalibration())
    assert row["selected"]
