"""Contract adapter: one configurable ORCA single point per selected MMFF94 geometry.

VALIDATE, the expensive QM check: DFT HOMO-LUMO gap with ORCA (ORCA_BIN, else `orca` on PATH), starting
from the geometry PREDICT selected. Only the orca backend and gap targets are implemented; a PySCF
backend and TADF S1/T1 calculations are not.
"""
import re
import shutil

from molcurator.chem.calculations import orca_gap, require_gap_target, run, safe_id
from molcurator.chem.geometry import xyz_symbols
from molcurator.chem.settings import load_settings
from molcurator.chem.tracking import calculate
from molcurator.schemas import Prediction, PropertyTarget, QMResult, QMSettings, Status


def validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]:
    """QM value of the target property for each selected molecule (contract: Phase 2 plan, R2.2).

    Starts from each item's selected MMFF94 geometry (xyz_path). Returns exactly one QMResult per
    item, in the same order, with `method` naming the level of theory (e.g. "dft:B3LYP/def2-SVP").
    A failed calculation is returned with status "failed" and an error, never dropped.
    No retries, TADF, or conformer aggregation: each item can invoke ORCA once, and attempt.json
    records attempts, including failures. The agent passes only the QM batch, already trimmed to
    the remaining QM budget (R4.2).
    """
    results = []
    method = f"dft:{qm.functional}/{qm.basis}"
    for item in items:
        try:
            require_gap_target(target)
            cid = safe_id(item.candidate_id)
            if qm.backend != "orca":
                raise ValueError("iteration 1 supports the orca backend only")
            for token in (qm.functional, qm.basis):
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+*(),./-]*", token):
                    raise ValueError("QM functional and basis must be single keyword tokens")
            if item.status is not Status.ok or item.xyz_path is None:
                raise ValueError("successful prediction and selected geometry required")
            geometry = item.xyz_path.resolve()
            xyz_symbols(geometry)
            folder = geometry.parent / "calculations" / cid / "orca"
            folder.mkdir(parents=True, exist_ok=True)
            settings = load_settings()
            shutil.copyfile(geometry, folder / "geometry.xyz")
            (folder / "gap.inp").write_text(
                f"! {qm.functional} {qm.basis} TightSCF\n"
                f"%pal nprocs {settings.orca_nprocs} end\n"
                f"%maxcore {settings.orca_maxcore_mb}\n* xyzfile 0 1 geometry.xyz\n")
            value = calculate(
                folder, "orca", ["gap.inp"],
                {"gap.inp": (folder / "gap.inp").read_bytes(),
                 "geometry.xyz": (folder / "geometry.xyz").read_bytes()},
                orca_gap, run, settings, dict(candidate_id=item.candidate_id, method=method))
            results.append(QMResult(candidate_id=item.candidate_id, method=method,
                                    status=Status.ok, value=value))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            results.append(QMResult(candidate_id=item.candidate_id, method=method,
                                    status=Status.failed, error=error))
    return results
