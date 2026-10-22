"""Stop one molecule before electronic work unless conformer preparation yields valid XYZ."""
from datetime import datetime, timezone
import uuid

from .fileio import atomic_json, native_path


class PreparationError(ValueError):
    def __init__(self, stage, code, message, **details):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.details = details


def prepare_geometry(candidate, folder, builder, xyz_validator):
    """Return prepared geometry only after validation; never invoke an electronic backend."""
    folder = native_path(folder)
    history = folder / "prevalidation"
    history.mkdir(exist_ok=True)
    event = history / (uuid.uuid4().hex + ".json")
    record = dict(candidate_id=candidate.id, smiles=candidate.smiles,
                  status="started", stage="conformer_preparation", code=None,
                  electronic_calls_allowed=False, electronic_calls_attempted=0,
                  started_at=datetime.now(timezone.utc).isoformat())

    def save():
        atomic_json(event, record)
        atomic_json(folder / "prevalidation.json", record)

    save()
    initial = folder / "initial.xyz"
    try:
        initial.unlink(missing_ok=True)
        for name in ("geometry_report.json", "geometry_report.md"):
            (folder / name).unlink(missing_ok=True)
        xyz, report = builder(candidate.smiles)
        record.update(stage="xyz_export", code="xyz_creation_failed")
        if not isinstance(xyz, str) or not xyz.strip():
            raise PreparationError("xyz_export", "missing_xyz", "RDKit produced no XYZ geometry")
        try:
            initial.write_text(xyz, encoding="utf-8")
        except OSError as exc:
            raise PreparationError("xyz_export", "xyz_write_failed", str(exc)) from exc
        if not initial.is_file():
            raise PreparationError("xyz_export", "missing_xyz_file", "XYZ file was not created")
        try:
            symbols = xyz_validator(initial)
            if not symbols:
                raise ValueError("XYZ contains no atoms")
        except Exception as exc:
            raise PreparationError("xyz_validation", "invalid_xyz", str(exc)) from exc
        record.update(status="ok", stage="complete", code="geometry_ready",
                      electronic_calls_allowed=True, atom_count=len(symbols),
                      n_embedded=report.get("n_embedded"), n_converged=report.get("n_converged"),
                      details=dict(formal_charge=report.get("formal_charge"),
                                   radical_electrons=report.get("radical_electrons")))
        return xyz, report, initial
    except Exception as exc:
        if isinstance(exc, PreparationError):
            record.update(stage=exc.stage, code=exc.code, details=exc.details)
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                      electronic_calls_allowed=False)
        if record["code"] is None:
            record["code"] = "geometry_preparation_failed"
        initial.unlink(missing_ok=True)
        raise
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
