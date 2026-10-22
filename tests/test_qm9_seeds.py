# Tests for chem/qm9.py and `molcurator seeds`: QM9 seed suggestions by property window.
import pandas as pd
import pytest
from rdkit import Chem
from typer.testing import CliRunner

from molcurator.chem.qm9 import HARTREE_EV, rejection, suggest_seeds
from molcurator.cli import app

# (smiles, gap in eV): usable seeds with distinct scaffolds, plus one of each rejected kind
GOOD = [("c1ccc2[nH]ccc2c1", 3.05), ("c1ccncc1", 3.15), ("Oc1ccccc1", 3.25),
        ("c1ccoc1", 3.35), ("Nc1ccncc1", 3.45), ("c1ccsc1", 3.42)]
BAD = [("C[NH3+].[O-]C=O", 3.2), ("CCCC=O", 3.2), ("C1CN1", 3.2), ("N=C1C=CC=CN1", 3.2),
       ("O=C1CCCC1=O", 3.2)]
OUTSIDE = [("c1ccc2ccccc2c1", 5.0)]


@pytest.fixture
def qm9(tmp_path):
    rows = [dict(mol_id=f"gdb_{i}", smiles=s, gap=ev / HARTREE_EV, mu=1.0)
            for i, (s, ev) in enumerate(GOOD + BAD + OUTSIDE)]
    path = tmp_path / "qm9.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.mark.parametrize("smiles,reason", [
    ("C[NH3+].[O-]C=O", "charged"), ("CCCC=O", "acyclic"), ("C1CN1", "3-ring"),
    ("N=C1C=CC=CN1", "exocyclic imine"), ("O=C1CCCC1=O", "alpha-dione"), ("c1ccccc1", None)])
def test_rejection(smiles, reason):
    assert rejection(Chem.MolFromSmiles(smiles)) == reason


def test_suggests_spread_distinct_scaffolds_in_window(qm9):
    seeds, counts = suggest_seeds(pd.read_csv(qm9), "gap", 3.0, 3.5, n=5)
    assert len(seeds) == 5 and seeds["murcko_scaffold"].is_unique
    assert seeds["qm9_gap"].between(3.0, 3.5).all() and seeds["qm9_gap"].is_monotonic_increasing
    assert (seeds["unit"] == "eV").all() and (seeds["source"] == "QM9").all()
    assert counts["in window"] == len(GOOD + BAD) and counts["usable"] == len(GOOD)
    # one per 0.1 eV bin: thiophene (3.42) and 4-aminopyridine (3.45) share the last bin
    assert len({round(v // 0.1) for v in seeds["qm9_gap"]}) == 5
    for s in seeds["smiles"]:
        assert Chem.MolToSmiles(Chem.MolFromSmiles(s)) == s


def test_one_sided_window_and_short_pool(qm9):
    seeds, _ = suggest_seeds(pd.read_csv(qm9), "gap", hi=3.2, n=10)
    assert list(seeds["smiles"]) == ["c1ccc2[nH]ccc2c1", "c1ccncc1"]  # all there is, no repeats


def test_deterministic(qm9):
    df = pd.read_csv(qm9)
    assert suggest_seeds(df, "gap", 3.0, 3.5, 3)[0].equals(suggest_seeds(df, "gap", 3.0, 3.5, 3)[0])


@pytest.mark.parametrize("kwargs", [dict(prop="foo", lo=1), dict(prop="gap"),
                                    dict(prop="gap", lo=4, hi=3), dict(prop="gap", lo=3, n=0)])
def test_bad_arguments(qm9, kwargs):
    with pytest.raises(ValueError):
        suggest_seeds(pd.read_csv(qm9), **kwargs)


def test_cli_prints_and_writes_csv(qm9, tmp_path):
    out = tmp_path / "seeds.csv"
    result = CliRunner().invoke(app, ["seeds", "--property", "gap", "--min", "3.0", "--max", "3.5",
                                      "--n", "3", "--qm9", str(qm9), "--out", str(out)])
    assert result.exit_code == 0, result.output
    written = pd.read_csv(out)
    assert len(written) == 3 and all(s in result.output for s in written["smiles"])


def test_cli_empty_window_and_unknown_property(qm9):
    empty = CliRunner().invoke(app, ["seeds", "-p", "gap", "--min", "10", "--qm9", str(qm9)])
    assert empty.exit_code == 1 and "widen" in empty.output
    bad = CliRunner().invoke(app, ["seeds", "-p", "foo", "--min", "1", "--qm9", str(qm9)])
    assert bad.exit_code == 2
