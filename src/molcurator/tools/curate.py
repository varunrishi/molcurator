# CURATE: add verified molecules to the benchmark dataset.
#
# Writes CuratedEntry records (SMILES, XYZ structure, properties from every method,
# provenance) to the run folder data/runs/<run_id>/, e.g. dataset.csv + xyz/ files.
# Also handles deduplication against molecules already in the dataset.
import csv
from pathlib import Path

from molcurator.schemas import CuratedEntry

COLUMNS = ["id", "smiles", "xyz_path", "ml", "xtb", "qm", "qm_method", "validated",
           "parent", "round", "generator", "seeds"]  # fixed, so rows can be appended round after round


def dataset_row(entry: CuratedEntry, run_dir: Path) -> dict:
    """One dataset.csv row: a value at every level the molecule has; a missing level is empty (R11.3).
    Any property key other than ml/xtb is the QM value, named by its method."""
    qm = {k: v for k, v in entry.properties.items() if k not in ("ml", "xtb")}
    xyz = entry.xyz_path
    if xyz is not None and Path(xyz).is_relative_to(run_dir):
        xyz = Path(xyz).relative_to(run_dir)  # relative, so the run folder can be moved or shared
    return {"id": entry.id, "smiles": entry.smiles, "xyz_path": xyz or "",
            "ml": entry.properties.get("ml", ""), "xtb": entry.properties.get("xtb", ""),
            "qm": next(iter(qm.values()), ""), "qm_method": next(iter(qm), ""), "validated": entry.validated,
            **{k: entry.provenance.get(k, "") for k in ("parent", "round", "generator", "seeds")}}


def curate(entries: list[CuratedEntry], run_dir: Path) -> int:
    """Add verified molecules to the run's benchmark dataset (contract: Phase 2 plan, R2.2).

    Writes the entries (SMILES, geometry, properties per method, provenance) to the dataset
    in run_dir, and returns the dataset's total size. Must be idempotent: an entry whose id or
    canonical SMILES is already in the dataset is skipped, so re-running CURATE on resume
    (R7.2) never duplicates molecules.
    """
    run_dir = Path(run_dir)
    path = run_dir / "dataset.csv"
    rows = []
    if path.exists():
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    ids, smiles = {r["id"] for r in rows}, {r["smiles"] for r in rows}
    new = []
    for e in entries:
        if e.id not in ids and e.smiles not in smiles:  # idempotent: a resumed CURATE adds nothing (R7.2)
            new.append(dataset_row(e, run_dir))
            ids.add(e.id); smiles.add(e.smiles)
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, COLUMNS)
        if not path.stat().st_size:  # a new file gets the header first
            writer.writeheader()
        writer.writerows(new)
    return len(rows) + len(new)
