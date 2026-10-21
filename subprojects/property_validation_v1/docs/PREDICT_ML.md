# Trained molecular property prediction

Branch `tools/predict-ml` provides a portable trained Morgan-fingerprint ridge model and a binding to the exact shared PREDICT signature. A compatible trained model must be supplied. No pretrained artifact or accuracy/uncertainty claim is bundled; this is an optional baseline requiring independent scientific evaluation.

```python
from molcurator_property_validation.tools.predict_ml import MLPredictor
# tool = MLPredictor("trusted-model.json")
# predictions = tool.predict(candidates, config.target, run_dir / "xyz")
```

The generated Candidate list can be supplied unchanged. One shared Prediction is returned per molecule with original IDs/order and explicit failures. Supported model targets are HOMO, LUMO, gap (eV), or dipole magnitude (D). Requested units must match the trained target. Predictions have no geometry: prepare/supply XYZ separately for subsequent QM validation. ML never invokes xTB or ORCA.

For training with your own homogeneous reference labels, call `train_fingerprint_model(smiles, labels, reference_method=...)` in `molcurator_property_validation.ml`, then `model.save(path)`. Labels are finite arrays named by property. Training rejects canonical duplicates and records training identities, fingerprint settings, penalty, target units, reference method and software versions. Artifacts use JSON rather than executable pickle. Do not fit on held-out evaluation molecules or mix reference methods.

The tool saves per-request metadata in `xyz_dir/ml_predictions/<request>/predictions.json`, including model hash, declared reference method, predictions and unavailable uncertainty. These estimates must not be stored as actual ORCA observations. The agent owns model choice, applicability checks, selection, cumulative budgets and curation.

Offline tests establish training/loading/contract behavior only. Compare independent molecular predictions to a simple constant baseline and audit training/test overlap before using this model for expensive-call selection. The common package support files match the other focused tool PRs; no root files are modified.
