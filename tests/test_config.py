"""load_config: seeds inline or from a CSV (seeds_file)."""
from pathlib import Path

import pytest

from molcurator.config import load_config

ROOT = Path(__file__).parents[1]


def write_config(tmp_path: Path, seeds_lines: str) -> Path:
    path = tmp_path / "run.yaml"
    path.write_text(f"target:\n  name: homo_lumo_gap\n  min: 3.0\n  max: 3.5\n{seeds_lines}")
    return path


def test_seeds_file_is_read_relative_to_the_config(tmp_path):
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "s.csv").write_text("smiles,mol_id\nC1=CC=CC=C1,a\n\nOCC,b\n,c\n")
    config = load_config(write_config(tmp_path, "seeds_file: seeds/s.csv\n"))
    assert config.seeds == ["c1ccccc1", "CCO"]  # canonicalised, in file order; blank rows skipped


def test_seeds_and_seeds_file_together_is_an_error(tmp_path):
    (tmp_path / "s.csv").write_text("smiles\nCCO\n")
    with pytest.raises(ValueError, match="not both"):
        load_config(write_config(tmp_path, "seeds: [CCO]\nseeds_file: s.csv\n"))


def test_seeds_file_needs_a_smiles_column(tmp_path):
    (tmp_path / "s.csv").write_text("smi\nCCO\n")
    with pytest.raises(ValueError, match="no 'smiles' column"):
        load_config(write_config(tmp_path, "seeds_file: s.csv\n"))


def test_an_empty_seeds_file_is_rejected(tmp_path):
    (tmp_path / "s.csv").write_text("smiles\n")
    with pytest.raises(ValueError, match="seeds"):
        load_config(write_config(tmp_path, "seeds_file: s.csv\n"))


def test_homo_lumo_preset_uses_the_qm9_seeds():
    config = load_config(ROOT / "configs" / "homo_lumo.yaml")
    assert len(config.seeds) == 10  # data/seeds/homo_lumo.csv
