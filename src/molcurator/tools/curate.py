# CURATE: add verified molecules to the benchmark dataset.
#
# Writes CuratedEntry records (SMILES, XYZ structure, properties from every method,
# provenance) to the run folder data/runs/<run_id>/, e.g. dataset.csv + xyz/ files.
# Also handles deduplication against molecules already in the dataset.
from pathlib import Path

from molcurator.schemas import CuratedEntry


def curate(entries: list[CuratedEntry], run_dir: Path) -> int:
    """Add verified molecules to the run's benchmark dataset (contract: Phase 2 plan, R2.2).

    Writes the entries (SMILES, geometry, properties per method, provenance) to the dataset
    in run_dir, and returns the dataset's total size. Must be idempotent: an entry whose id or
    canonical SMILES is already in the dataset is skipped, so re-running CURATE on resume
    (R7.2) never duplicates molecules.
    """
    raise NotImplementedError("curate() is built in Phase 1 (tools); use FakeToolset in tests")
