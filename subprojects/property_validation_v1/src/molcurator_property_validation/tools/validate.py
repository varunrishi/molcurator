"""Contract adapter: one configurable ORCA single point per selected MMFF94 geometry."""
import json
import re
import shutil

from molcurator_property_validation.chem.calculations import orca_gap, require_gap_target, run, safe_id
from molcurator_property_validation.chem.geometry import xyz_symbols
from molcurator.schemas import Prediction, PropertyTarget, QMResult, QMSettings, Status


def validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]:
    """Keep input IDs/order and failures; no retries, TADF, or conformer aggregation.

    Each item can invoke ORCA once. attempt.json records attempts, including failures;
    the orchestrator remains responsible for its overall QM budget.
    """
    results = []
    method = f"dft:{qm.functional}/{qm.basis}"
    for item in items:
        attempt = None
        record = dict(candidate_id=item.candidate_id, method=method, qm_calls_attempted=0)
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
            attempt = folder / "attempt.json"
            shutil.copyfile(geometry, folder / "geometry.xyz")
            (folder / "gap.inp").write_text(
                f"! {qm.functional} {qm.basis} TightSCF\n"
                "%pal nprocs 1 end\n%maxcore 2000\n* xyzfile 0 1 geometry.xyz\n")
            record.update(qm_calls_attempted=1, status="started", geometry_path=str(geometry))
            attempt.write_text(json.dumps(record, indent=2))
            run("ORCA_BIN", "orca", ["gap.inp"], folder, folder / "orca.out")
            value = orca_gap((folder / "orca.out").read_text(errors="replace"))
            record.update(status="ok", value=value)
            attempt.write_text(json.dumps(record, indent=2))
            results.append(QMResult(candidate_id=item.candidate_id, method=method,
                                    status=Status.ok, value=value))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt is not None:
                record.update(status="failed", error=error)
                try:
                    attempt.write_text(json.dumps(record, indent=2))
                except OSError:
                    pass  # Reporting failure must not discard the molecule's result.
            results.append(QMResult(candidate_id=item.candidate_id, method=method,
                                    status=Status.failed, error=error))
    return results
