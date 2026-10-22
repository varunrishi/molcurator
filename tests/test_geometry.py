# Tests for chem/geometry.py: conformer selection and XYZ reading on small molecules.
import pytest

from molcurator.chem.geometry import (
    GeometryError,
    charge_multiplicity_comment,
    lowest_ff_conformer,
    read_charge_multiplicity,
    read_xyz,
    with_comment,
)
from molcurator.chem.settings import ChemistrySettings

FAST = ChemistrySettings(nconfs=5)


def test_lowest_conformer_report_and_xyz(tmp_path):
    xyz, report = lowest_ff_conformer("CCCC", FAST)
    assert report["n_unique"] >= 1 and 0 < report["selected_ff_boltzmann_weight"] <= 1
    assert report["formal_charge"] == 0 and report["radical_electrons"] == 0
    path = tmp_path / "butane.xyz"
    path.write_text(with_comment(xyz, charge_multiplicity_comment(0, 1)))
    elements, coordinates = read_xyz(path)
    assert elements.count("C") == 4 and len(coordinates) == 14
    assert read_charge_multiplicity(path) == (0, 1)


def test_charge_and_radicals_are_reported():
    assert lowest_ff_conformer("C[NH3+]", FAST)[1]["formal_charge"] == 1
    assert lowest_ff_conformer("[CH3]", FAST)[1]["radical_electrons"] == 1


@pytest.mark.parametrize("smiles", ["C1CC", "CC.O", ""])
def test_invalid_or_disconnected_smiles_fail(smiles):
    with pytest.raises(GeometryError) as err:
        lowest_ff_conformer(smiles, FAST)
    assert err.value.stage == "structure"


@pytest.mark.parametrize("text", ["", "2\nc\nH 0 0 0\n", "1\nc\nXx 0 0 0\n", "1\nc\nH 0 0 nan\n", "1\nc\nH 0 0\n"])
def test_malformed_xyz_is_rejected(tmp_path, text):
    path = tmp_path / "bad.xyz"
    path.write_text(text)
    with pytest.raises(ValueError):
        read_xyz(path)


def test_missing_comment_means_neutral_singlet(tmp_path):
    path = tmp_path / "plain.xyz"
    path.write_text("1\n\nH 0 0 0\n")
    assert read_charge_multiplicity(path) == (0, 1)
