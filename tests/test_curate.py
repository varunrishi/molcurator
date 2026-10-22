"""tools/curate.py: dataset.csv rows, values at every level, and idempotence (Phase 2, R11.3, R7.2)."""
import csv

from molcurator.schemas import CuratedEntry
from molcurator.tools.curate import COLUMNS, ML_ONLY_COLUMNS, curate, export_ml_only


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


def test_ml_only_export_keeps_only_molecules_without_xtb_or_qm(tmp_path):
    """The end-of-run export: only rows with just an ML value, without the columns that are always empty."""
    assert export_ml_only(tmp_path) == 0  # nothing curated yet: header only
    entries = [CuratedEntry(id="r1-c001", smiles="c1ccsc1", properties={"xtb": 3.3}, provenance={"round": "1"}),
               CuratedEntry(id="r1-c002", smiles="CCO", properties={"ml": 3.2}, provenance={"round": "1"}),
               CuratedEntry(id="r1-c003", smiles="CCN", properties={"ml": 3.1, "dft:B3LYP/def2-SVP": 3.4},
                            provenance={"round": "1"})]
    curate(entries, tmp_path)
    assert export_ml_only(tmp_path) == export_ml_only(tmp_path) == 1  # rebuilt each time, never appended
    with (tmp_path / "dataset_ml_only.csv").open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ML_ONLY_COLUMNS
    assert [(r["id"], r["ml"], r["round"]) for r in rows] == [("r1-c002", "3.2", "1")]
