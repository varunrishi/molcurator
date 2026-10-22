# Tests for tools/predict.py: MMFF94 geometry + GFN2-xTB (tblite) on small molecules, and
# B97-3c TD-DFT through ORCA for a target xTB cannot give.
import inspect
import json

import pytest

from molcurator.agent.toolset import Toolset
from molcurator.chem.settings import ChemistrySettings, active_settings
from molcurator.config import PredictSettings, RunConfig
from molcurator.schemas import Candidate, PropertyTarget, Status
from molcurator.tools import predict as predict_module
from molcurator.tools.predict import (
    DFT_METHOD,
    XTB_METHOD,
    check_predict_level,
    default_method,
    predict,
    predict_at,
    predict_with_method,
)
from tests.conftest import needs_orca

GAP = PropertyTarget(name="homo_lumo_gap", min=3, max=4)
EST = PropertyTarget(name="s1_t1_gap", max=0.3)


@pytest.fixture(autouse=True)
def fast_settings():
    token = active_settings.set(ChemistrySettings(nconfs=5))
    yield
    active_settings.reset(token)


def _candidates(*pairs):
    return [Candidate(id=i, smiles=s, parent_smiles=s, round=1, generator="test") for i, s in pairs]


def test_default_method_follows_target():
    assert default_method(GAP) == XTB_METHOD
    assert default_method(EST) == DFT_METHOD


def test_order_ids_failures_and_geometry_are_kept(tmp_path):
    results = predict(_candidates(("eth", "CCO"), ("bad", "C1CC"), ("bz", "c1ccccc1")), GAP, tmp_path)
    assert [r.candidate_id for r in results] == ["eth", "bad", "bz"]
    assert [r.status for r in results] == [Status.ok, Status.failed, Status.ok]
    assert "GeometryError" in results[1].error
    assert results[2].value == pytest.approx(4.83, abs=0.1)  # GFN2-xTB benzene gap, eV
    assert results[0].xyz_path == (tmp_path / "eth.xyz").resolve()
    assert results[0].xyz_path.read_text().splitlines()[1] == "charge=0 multiplicity=1"
    record = json.loads((tmp_path / "calculations/eth/predict.json").read_text())
    assert record["backend"] == "xtb" and record["method_label"] == "xtb:GFN2-xTB"


def test_radical_gets_doublet_and_unsafe_id_fails(tmp_path):
    results = predict(_candidates(("methyl", "[CH3]"), ("../x", "C")), GAP, tmp_path)
    assert results[0].status is Status.ok
    assert results[0].xyz_path.read_text().splitlines()[1] == "charge=0 multiplicity=2"
    assert results[1].status is Status.failed and "candidate id" in results[1].error


def test_xtb_is_never_upgraded_to_dft(tmp_path):
    result = predict_with_method(_candidates(("eth", "CCO")), EST, tmp_path, "gfn2-xtb")[0]
    assert result.status is Status.failed and "use molcurator.chem.orca" in result.error


def test_repeat_attempt_removes_stale_geometry(tmp_path):
    (tmp_path / "bad.xyz").write_text("stale")
    predict(_candidates(("bad", "C1CC")), GAP, tmp_path)
    assert not (tmp_path / "bad.xyz").exists()


@needs_orca
def test_tddft_prediction_for_singlet_triplet_gap(tmp_path):
    result = predict(_candidates(("form", "C=O")), EST, tmp_path)[0]
    assert result.status is Status.ok, result.error
    record = json.loads((tmp_path / "calculations/form/predict.json").read_text())
    assert record["method_label"] == "dft:B97-3c" and record["details"]["s1_ev"] > record["details"]["t1_ev"]


# --- configurable PREDICT level (predict.method / predict.basis) ---

@pytest.mark.parametrize(("target", "method", "basis", "qm", "message"), [
    ("s1_t1_gap", "gfn2-xtb", None, (None, None), "cannot give s1_t1_gap"),
    ("homo_lumo_gap", "B97-3c", "def2-TZVP", (None, None), "would be ignored"),
    ("homo_lumo_gap", "gfn1-xtb", "def2-SVP", (None, None), "would be ignored"),
    ("homo_lumo_gap", None, "def2-TZVP", (None, None), "needs predict.method"),
    ("homo_lumo_gap", "PBE0", None, ("pbe0", "def2-SVP"), "higher level"),  # basis defaults to def2-SVP
    ("s1_t1_gap", None, None, ("B97-3c", "def2-SVP"), "higher level"),  # the -3c default ignores any basis
])
def test_impossible_predict_levels_are_refused(target, method, basis, qm, message):
    with pytest.raises(ValueError, match=message):
        check_predict_level(target, method, basis, *qm)


@pytest.mark.parametrize(("target", "method", "basis", "qm"), [
    ("homo_lumo_gap", None, None, ("B3LYP", "def2-SVP")),
    ("homo_lumo_gap", "gfn1-xtb", None, ("B3LYP", "def2-SVP")),
    ("homo_lumo_gap", "PBE0", "def2-SVP", ("PBE0", "def2-TZVP")),
    ("s1_t1_gap", "r2SCAN-3c", None, ("PBE0", "def2-SVP")),
    ("homo_lumo_gap", "B3LYP", None, (None, None)),  # same as the qm default, but QM is off
])
def test_workable_predict_levels_pass(target, method, basis, qm):
    check_predict_level(target, method, basis, *qm)


def test_run_config_checks_the_predict_level():
    base = {"target": {"name": "s1_t1_gap", "max": 0.2}, "seeds": ["CCO"]}
    with pytest.raises(ValueError, match="cannot give s1_t1_gap"):
        RunConfig.model_validate({**base, "predict": {"method": "gfn2-xtb"}})
    config = RunConfig.model_validate({**base, "predict": {"method": "PBE0", "basis": "def2-SVP"},
                                       "qm": {"functional": "PBE0", "basis": "def2-TZVP"}})
    assert (config.predict.method, config.predict.basis) == ("PBE0", "def2-SVP")


def test_configured_level_reaches_predict_and_keeps_the_contract(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(predict_module, "predict_with_method",
                        lambda c, t, d, method, basis=None: seen.append((method, basis)) or [])
    tools = Toolset.default(PredictSettings(method="PBE0", basis="def2-TZVP"))
    assert list(inspect.signature(tools.predict).parameters) == ["candidates", "target", "xyz_dir"]
    tools.predict([], GAP, tmp_path)
    assert seen == [("PBE0", "def2-TZVP")]
    assert Toolset.default(PredictSettings()).predict is predict and predict_at(None) is predict


@needs_orca
def test_dft_prediction_at_a_configured_level(tmp_path):
    result = predict_at("PBE0", "def2-SVP")(_candidates(("eth", "CCO")), GAP, tmp_path)[0]
    assert result.status is Status.ok, result.error
    record = json.loads((tmp_path / "calculations/eth/predict.json").read_text())
    assert record["method_label"] == "dft:PBE0/def2-SVP" and record["backend"] == "orca"
