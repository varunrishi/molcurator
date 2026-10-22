# Tests for tools/validate.py: ORCA single points at PREDICT's geometry. Argument handling
# runs without ORCA (the backend is replaced); the real calculation needs ORCA.
from pathlib import Path

import pytest

from molcurator.chem.settings import ChemistrySettings, active_settings
from molcurator.schemas import Prediction, PropertyTarget, QMSettings, Status
from molcurator.tools import validate as validate_module
from molcurator.tools.validate import validate
from tests.conftest import needs_orca

GAP = PropertyTarget(name="homo_lumo_gap", min=3, max=12)
WATER = "3\ncharge=0 multiplicity=1\nO 0 0 0.1173\nH 0 0.7572 -0.4692\nH 0 -0.7572 -0.4692\n"


@pytest.fixture(autouse=True)
def fast_settings():
    token = active_settings.set(ChemistrySettings(nconfs=5))
    yield
    active_settings.reset(token)


def _prediction(tmp_path: Path, cid: str = "w", text: str = WATER) -> Prediction:
    path = tmp_path / f"{cid}.xyz"
    path.write_text(text)
    return Prediction(candidate_id=cid, status=Status.ok, value=10.0, xyz_path=path)


def test_charge_multiplicity_and_settings_reach_the_backend(tmp_path, monkeypatch):
    seen = {}

    def fake(elements, coordinates, prop, method, basis, charge, multiplicity, workdir, settings, extra_keywords):
        seen.update(prop=prop, method=method, basis=basis, charge=charge, multiplicity=multiplicity,
                    extra=extra_keywords, natoms=len(elements))
        return {"success": True, "value": 9.5, "method": method, "basis": basis, "backend": "orca"}

    monkeypatch.setattr(validate_module, "calculate_property", fake)
    text = WATER.replace("charge=0 multiplicity=1", "charge=1 multiplicity=2")
    result = validate([_prediction(tmp_path, text=text)], GAP, QMSettings(functional="PBE0", basis="def2-TZVP"))[0]
    assert result.status is Status.ok and result.value == 9.5 and result.method == "dft:PBE0/def2-TZVP"
    assert seen == {"prop": "homo_lumo_gap", "method": "PBE0", "basis": "def2-TZVP", "charge": 1,
                    "multiplicity": 2, "extra": ["TightSCF"], "natoms": 3}


def test_failures_are_returned_in_order(tmp_path):
    items = [Prediction(candidate_id="f", status=Status.failed, error="xTB failed"),
             _prediction(tmp_path, "g", "not an xyz")]
    results = validate(items, GAP, QMSettings())
    assert [r.candidate_id for r in results] == ["f", "g"]
    assert all(r.status is Status.failed for r in results)
    assert validate([_prediction(tmp_path)], GAP, QMSettings(backend="pyscf"))[0].error.endswith("use orca")


@needs_orca
def test_real_orca_gap(tmp_path):
    result = validate([_prediction(tmp_path)], GAP, QMSettings(functional="B3LYP", basis="def2-SVP"))[0]
    assert result.status is Status.ok, result.error
    assert result.method == "dft:B3LYP/def2-SVP" and 8 < result.value < 10
    assert (tmp_path / "calculations/w/validate.json").is_file()
