# Tests for chem/xtb.py: GFN2-xTB through tblite on water (no binary needed; < 1 s each,
# except frequencies). Reference values match ORCA's built-in GFN2-xTB on the same geometry.
import numpy as np
import pytest

from molcurator.chem.xtb import PROPERTIES, calculate_property, tool_definition

WATER = (["O", "H", "H"], [[0.0, 0.0, 0.1173], [0.0, 0.7572, -0.4692], [0.0, -0.7572, -0.4692]])


def _calc(prop, molecule=WATER, **kwargs):
    r = calculate_property(*molecule, prop, **kwargs)
    assert r["success"], r.get("error")
    return r


def test_energy_and_gap_match_orca_xtb():
    assert _calc("energy")["value"] == pytest.approx(-5.07037076, abs=1e-6)
    gap = _calc("homo_lumo_gap")
    assert gap["value"] == pytest.approx(14.6297, abs=1e-3)
    assert gap["method"] == "GFN2-xTB"


def test_gradient_forces_and_dipole():
    grad = _calc("gradient")["value"]
    assert -np.asarray(grad) == pytest.approx(np.asarray(_calc("forces")["value"]), abs=1e-12)
    assert _calc("dipole_moment")["value"] == pytest.approx(2.27, abs=0.01)  # debye


def test_optimisation_then_frequencies():
    opt = _calc("optimized_geometry")
    assert opt["details"]["converged"]
    freq = _calc("frequencies", (WATER[0], opt["value"]))
    assert len(freq["value"]) == 3 and freq["details"]["n_imaginary"] == 0
    assert 1450 < freq["value"][0] < 1650  # H-O-H bend


def test_linear_molecule_keeps_one_stretch():
    co = _calc("frequencies", (["C", "O"], [[0, 0, 0], [0, 0, 1.128]]))
    assert len(co["value"]) == 1


def test_open_shell_charged_and_solvated_runs():
    assert _calc("homo_lumo_gap", (["O", "H"], [[0, 0, 0], [0, 0, 0.97]]), multiplicity=2)["value"] > 0
    assert _calc("ionization_potential")["value"] > 0
    gas, water = _calc("energy")["value"], _calc("energy", solvent="water")["value"]
    assert water < gas


@pytest.mark.parametrize(("args", "message"), [
    ({"property_name": "s1_t1_gap"}, "chem.orca"),
    ({"property_name": "colour"}, "unknown property"),
    ({"property_name": "energy", "method": "B3LYP"}, "unknown xTB method"),
    ({"property_name": "energy", "multiplicity": 2}, "impossible"),
])
def test_requests_xtb_cannot_answer_fail_clearly(args, message):
    r = calculate_property(*WATER, **args)
    assert not r["success"] and message in r["error"]


def test_tool_definition_lists_every_property():
    assert tool_definition()["input_schema"]["properties"]["property_name"]["enum"] == sorted(PROPERTIES)
