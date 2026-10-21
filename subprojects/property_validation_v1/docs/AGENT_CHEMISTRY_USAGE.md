# Property predictor integration with the agent

The contribution's primary interface is **property prediction for generated molecules**. Generation, backend choice, screening/ranking policy, QM budgets, graph routing and persistent curation belong to the main agent. All implementation and artifacts of this contribution remain under the subproject folder.

## Bind to the existing PREDICT contract

```python
from molcurator_property_validation import PredictorSettings, PropertyPredictor

xtb_tool = PropertyPredictor(PredictorSettings(backend="xtb"))
# The team's exact signature and Prediction result models:
# predictions = xtb_tool.predict(candidates, target, xyz_dir)
```

The target's name chooses the requested property; units must be eV for `homo`, `lumo`, `homo_lumo_gap`, and D for `dipole`. Unsupported targets/units return per-input failures. Physics results return geometries at `xyz_dir/<candidate_id>.xyz`; request-specific method metadata and rich results stay under `xyz_dir/property_predictions/`. An already-created XYZ directory is accepted. The agent explicitly injects this callable; no root tool or schema is patched.

For an ML callable use `PropertyPredictor(PredictorSettings(backend="ml", model_path=...)).predict`. ML returns no geometry. A reference-calculation step must prepare/supply geometry separately; do not pass an ML prediction with no geometry blindly into the older VALIDATE adapter.

## Rich multi-property interface

```python
from pathlib import Path
from molcurator.schemas import QMSettings
from molcurator_property_validation import PredictorSettings, predict_properties

# candidates is the list emitted by the team's generator.
# settings = PredictorSettings(
#     backend="orca", properties=["homo", "lumo", "homo_lumo_gap", "dipole"],
#     qm=QMSettings(backend="orca", functional="B3LYP", basis="def2-SVP"),
# )
# results = predict_properties(candidates, settings, Path("runs/property-request-001"))
```

Use a new output directory for the rich API. Results retain input IDs/order and contain `values`, `units`, `method`, `backend`, `xyz_path`, `errors`, and `metadata`. Overall status is failed if any requested property is unavailable; available values remain explicit. `result.as_prediction(property_name)` converts one available property to the unchanged shared model and reports failure if that property is missing. Keep the rich record alongside the shared result because the shared schema has no method/uncertainty/multiple-property fields.

## Backend and geometry behavior

- **xTB:** one lowest-converged-FF geometry -> one GFN2-xTB optimization. Geometry reports contain the sampled FF Boltzmann weight at 298.15 K. No ORCA calculation occurs.
- **ORCA:** default geometry preparation is the same xTB pipeline, then one configured ground-state ORCA single point. `geometry="force_field"` skips xTB and uses the lowest FF minimum. `xyz_paths={candidate_id: path}` uses supplied XYZ instead. Supplied XYZ composition is checked against SMILES including hydrogens, but this check does not prove stereochemical identity; the caller owns geometry provenance. Method and geometry policy must both match for reference/calibration comparisons.
- **ML:** load a separately trained `FingerprintModel` JSON. It consumes SMILES, uses no embedding or QM, and returns only properties trained into the artifact. The record includes the artifact hash, declared reference method, and `uncertainty="not_available"`. No model is automatically trained or fetched.

Set process `XTB_BIN` and `ORCA_BIN`; `.env` is not loaded by the tool. `MOLCURATOR_QC_TIMEOUT_S` controls each physics process timeout (600 seconds by default). ORCA uses one thread and 2000 MB maxcore. Install using the [subproject README](../README.md), and run real chemistry on allocated compute nodes.

## Budget and failure responsibilities

The agent decides how many molecules to send to each backend before dispatch. One ORCA molecule makes at most one ORCA attempt, without retries; default geometry preparation additionally makes one xTB optimization. ORCA `attempt.json` and result metadata record failed attempts as well. These are per-request records, not a cumulative campaign ledger. Configuration/model errors fail before a request starts where possible; per-molecule chemistry and missing properties remain failed records with their IDs.

The predictor does not implement checkpoint/resume, cumulative quotas, a persistent calculation cache, human approval or the complete graph. It never decides whether a molecule is a true target hit. Use actual reference values with method labels to make that decision, then construct/persist CuratedEntry records in the main agent. ML estimates and calibrated xTB estimates must not be stored as if they were ORCA observations.

## Existing compatibility utilities

The earlier `molcurator_property_validation.tools.predict.predict` remains the xTB gap-only contract adapter. `tools.validate.validate` remains its ORCA gap reference adapter. The optional `tools.chemistry.run_chemistry_round` helper combines calibrated selection and entry preparation for the earlier HOMO–LUMO experiment; it is not required for the property predictor and does not run automatically.

The frozen calibrated ranking utility remains separate from trained molecular ML. Its B3LYP calibration evidence does not establish accuracy for a new ridge model, another method, or another property. The root main project still owns all agent decisions and persistent CURATE.
