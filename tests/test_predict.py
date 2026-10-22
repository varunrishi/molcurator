# Tests for tools/predict.py: MMFF94 geometry + GFN2-xTB (tblite) on small molecules, and
# B97-3c TD-DFT through ORCA for a target xTB cannot give.
import json

import pytest

from molcurator.chem.settings import ChemistrySettings, active_settings
from molcurator.schemas import Candidate, PropertyTarget, Status
from molcurator.tools.predict import DFT_METHOD, XTB_METHOD, default_method, predict, predict_with_method
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
