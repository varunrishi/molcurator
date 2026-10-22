"""Tests of saved artifacts and routing behavior; no live chemistry calculations."""
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("joblib")
pytest.importorskip("sklearn")
pytest.importorskip("pandas")
pytest.importorskip("rdkit")

from .router import CalibratedRouter
from .verify_router import main as verify_routing

BASE = Path(__file__).resolve().parent

def test_calibration_and_routing_invariants(tmp_path):
    verify_routing(tmp_path)
    checks = json.loads((tmp_path / "verification.json").read_text())
    assert len(checks) == 16 and all(checks.values())

@pytest.mark.parametrize("model", ["random", "scaffold"])
def test_saved_model_preserves_batch_identity_and_interval_nesting(model):
    router = CalibratedRouter(BASE / "models" / f"{model}_calibrated_router.joblib")
    smiles = router.artifact["training_smiles"][0]
    results = router.route([{"id": "valid", "smiles": smiles}, {"id": "invalid", "smiles": "not_a_smiles"}])
    assert [row["candidate_id"] for row in results] == ["valid", "invalid"]
    assert results[1]["route"] == "input_review"
    assert results[1]["accepted_ml_value_ev"] is None
    row = results[0]
    assert row["interval95_ev"][0] <= row["interval90_ev"][0] <= row["ml_estimate_ev"] <= row["interval90_ev"][1] <= row["interval95_ev"][1]
    assert row["xyz_path"] is None

def test_artifact_checksums():
    manifest = json.loads((BASE / "SHA256SUMS.json").read_text())
    for relative, expected in manifest.items():
        assert hashlib.sha256((BASE / relative).read_bytes()).hexdigest() == expected, relative
