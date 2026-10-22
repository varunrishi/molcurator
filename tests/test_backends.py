# Tests for chem/backends.py: the xTB guard on VALIDATE, and the fallback that runs xTB
# through ORCA when tblite is unavailable (simulated by replacing tblite_error).
import json

import pytest

from molcurator.chem import backends
from molcurator.chem.settings import ChemistrySettings, active_settings
from molcurator.config import RunConfig
from molcurator.schemas import Candidate, Prediction, PropertyTarget, QMSettings, Status
from molcurator.tools import validate as validate_module
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate
from tests.conftest import needs_orca

WATER = (["O", "H", "H"], [[0.0, 0.0, 0.1173], [0.0, 0.7572, -0.4692], [0.0, -0.7572, -0.4692]])
GAP = PropertyTarget(name="homo_lumo_gap", min=3, max=12)
SETTINGS = ChemistrySettings(nconfs=5)


@pytest.fixture
def no_tblite(monkeypatch):
    monkeypatch.setattr(backends, "tblite_error", lambda: "ModuleNotFoundError: No module named 'tblite'")


def _calc(tmp_path, method, prop="homo_lumo_gap"):
    return backends.calculate_property(*WATER, prop, method, None, 0, 1, tmp_path, SETTINGS)


# --- VALIDATE refuses xTB ---

def test_xtb_validation_message_names_the_fix():
    message = backends.xtb_validation_message("gfn2-xtb")
    assert "'gfn2-xtb'" in message and "DFT method" in message
    assert backends.xtb_validation_message("B3LYP") is None


def test_validate_with_xtb_returns_the_warning_without_calculating(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_module, "calculate_property", lambda *a, **k: pytest.fail("must not calculate"))
    xyz = tmp_path / "w.xyz"
    xyz.write_text("3\ncharge=0 multiplicity=1\nO 0 0 0.1173\nH 0 0.7572 -0.4692\nH 0 -0.7572 -0.4692\n")
    item = Prediction(candidate_id="w", status=Status.ok, value=14.6, xyz_path=xyz)
    result = validate([item], GAP, QMSettings(functional="gfn2-xtb"))[0]
    assert result.status is Status.failed and "higher-level method" in result.error


def test_run_config_rejects_xtb_qm_unless_qm_is_off():
    base = {"target": {"name": "homo_lumo_gap", "min": 3}, "seeds": ["CCO"]}
    with pytest.raises(ValueError, match="higher-level method"):
        RunConfig.model_validate({**base, "qm": {"functional": "gfn1-xtb"}})
    assert not RunConfig.model_validate({**base, "qm": {"functional": "gfn2-xtb", "enabled": False}}).qm.enabled


# --- fallback to ORCA's built-in xTB ---

def test_tblite_is_the_xtb_engine_when_installed(tmp_path):
    assert backends.backend_for("gfn2-xtb") == "xtb" and backends.backend_for("B3LYP") == "orca"
    result = _calc(tmp_path, "gfn2-xtb")
    assert result["backend"] == "xtb" and not result["notes"]
    assert backends.method_label(result) == "xtb:GFN2-xTB"


def test_ipea1_has_no_orca_fallback(tmp_path, no_tblite):
    assert backends.backend_for("ipea1-xtb") == "orca"
    result = _calc(tmp_path, "ipea1-xtb")
    assert not result["success"] and "GFN2-xTB and GFN1-xTB" in result["error"]
    assert not any(tmp_path.iterdir())


@needs_orca
def test_orca_fallback_matches_tblite(tmp_path, monkeypatch):
    reference = _calc(tmp_path, "gfn2-xtb")
    monkeypatch.setattr(backends, "tblite_error", lambda: "ModuleNotFoundError: No module named 'tblite'")
    fallback = _calc(tmp_path, "gfn2-xtb")
    assert fallback["success"], fallback.get("error")
    assert fallback["backend"] == "orca" and "built-in xTB" in fallback["notes"][0]
    assert fallback["value"] == pytest.approx(reference["value"], abs=1e-3)  # ORCA prints 4 decimals
    assert backends.method_label(fallback) == backends.method_label(reference) == "xtb:GFN2-xTB"


@needs_orca
def test_predict_runs_on_the_fallback(tmp_path, no_tblite):
    token = active_settings.set(SETTINGS)
    try:
        result = predict([Candidate(id="eth", smiles="CCO", parent_smiles="CCO", round=1, generator="t")],
                         GAP, tmp_path)[0]
    finally:
        active_settings.reset(token)
    assert result.status is Status.ok, result.error
    record = json.loads((tmp_path / "calculations/eth/predict.json").read_text())
    assert record["backend"] == "orca" and record["method_label"] == "xtb:GFN2-xTB"


# --- run and batch targets: single-number properties, in the tools' units ---

@pytest.mark.parametrize(("name", "units", "expected"), [
    ("homo_lumo_gap", None, "eV"), ("dipole_moment", None, "debye"), ("dipole_moment", "D", "D"),
    ("energy", "hartree", "hartree"), ("polarizability", "bohr^3", "bohr^3"), ("g_tensor", None, ""),
])
def test_target_units_are_filled_in_or_accepted(name, units, expected):
    assert backends.check_target(name, units) == expected


@pytest.mark.parametrize(("name", "units", "message"), [
    ("gap", None, "Did you mean 'homo_lumo_gap'"),
    ("frequencies", None, "not a single-number property"),
    ("dipole_moment", "eV", "computes? in debye|compute in debye"),
    ("homo_lumo_gap", "kcal/mol", "compute in eV"),
])
def test_unusable_targets_are_refused(name, units, message):
    with pytest.raises(ValueError, match=message):
        backends.check_target(name, units)


def test_run_config_checks_target_and_fills_units():
    seeds = {"seeds": ["CCO"]}
    assert RunConfig.model_validate({**seeds, "target": {"name": "dipole_moment", "min": 2}}).target.units == "debye"
    with pytest.raises(ValueError, match="compute in debye"):
        RunConfig.model_validate({**seeds, "target": {"name": "dipole_moment", "min": 2, "units": "eV"}})
    with pytest.raises(ValueError, match="Did you mean 'homo_lumo_gap'"):
        RunConfig.model_validate({**seeds, "target": {"name": "gap", "min": 3}})
