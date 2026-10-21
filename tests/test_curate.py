"""tools/curate.py: dataset.csv rows, values at every level, and idempotence (Phase 2, R11.3, R7.2)."""
import csv

from molcurator.schemas import CuratedEntry
from molcurator.tools.curate import COLUMNS, curate


def test_curate_writes_one_row_per_molecule_and_is_idempotent(tmp_path):
    qm = CuratedEntry(id="r1-c004", smiles="c1ccsc1", xyz_path=tmp_path / "xyz" / "r1-c004.xyz", validated=True,
                      properties={"xtb": 3.31, "dft:B3LYP/def2-SVP": 3.18}, provenance={"round": "1"})
    ml_only = CuratedEntry(id="r2-c100", smiles="CCO", properties={"ml": 3.2}, provenance={"round": "2"})
    assert curate([qm, ml_only], tmp_path) == 2
    assert curate([qm, ml_only], tmp_path) == 2  # re-run, e.g. on resume: nothing added
    with (tmp_path / "dataset.csv").open(newline="") as f:
        reader = csv.DictReader(f)
        rows = {r["id"]: r for r in reader}
    assert reader.fieldnames == COLUMNS and len(rows) == 2
    row = rows["r1-c004"]
    assert (row["xyz_path"], row["xtb"], row["qm"], row["qm_method"], row["validated"]) == \
        ("xyz/r1-c004.xyz", "3.31", "3.18", "dft:B3LYP/def2-SVP", "True")
    assert (rows["r2-c100"]["ml"], rows["r2-c100"]["xtb"], rows["r2-c100"]["xyz_path"]) == ("3.2", "", "")
