"""Bind a separately trained fingerprint model to the unchanged PREDICT contract."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from molcurator.schemas import Prediction, Status
from molcurator_property_validation.ml import FingerprintModel


class MLPredictor:
    """No pretrained model, geometry, QM calculation or calibrated uncertainty is supplied."""

    def __init__(self, model_path):
        content = Path(model_path).read_bytes()
        self.model = FingerprintModel(json.loads(content.decode("utf-8-sig")))
        self.model_hash = hashlib.sha256(content).hexdigest()

    def predict(self, candidates, target, xyz_dir):
        results = []
        for candidate in candidates:
            try:
                definition = self.model.artifact["targets"].get(target.name)
                if definition is None or definition["units"] != target.units:
                    raise ValueError("requested property/units unavailable from this model")
                value = self.model.predict(candidate.smiles)[target.name]
                if target.name in ("homo_lumo_gap", "dipole") and value < 0:
                    raise ValueError("negative gap or dipole prediction")
                results.append(Prediction(candidate_id=candidate.id, status=Status.ok, value=value))
            except Exception as exc:
                results.append(Prediction(candidate_id=candidate.id, status=Status.failed,
                                          error=f"{type(exc).__name__}: {exc}"))
        folder = Path(xyz_dir) / "ml_predictions" / uuid4().hex
        folder.mkdir(parents=True)
        metadata = dict(backend="fingerprint_ridge", model_sha256=self.model_hash,
                        reference_method=self.model.artifact["reference_method"],
                        uncertainty="not_available", qm_calls_attempted=0,
                        target=target.model_dump(mode="json"),
                        predictions=[r.model_dump(mode="json") for r in results])
        (folder / "predictions.json").write_text(json.dumps(metadata, indent=2, allow_nan=False))
        return results
