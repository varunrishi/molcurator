# Property prediction ML: repeated splits, uncertainty and routing

This folder contains two trained ExtraTrees models with separate conformal calibration, runnable inference and routing code, the five-seed analysis with five plots, labelled data, split manifests, test predictions, and verification records. No model training is needed to use it.

## Quick start (Windows, Python 3.11)

From the repository root, enter `tests/property_prediction_ml`, then run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-inference.txt
.\.venv\Scripts\python.exe router.py --model models/random_calibrated_router.joblib --input routing_example.csv --output my_routes.json
```

On Linux use `python3.11 -m venv .venv` and `.venv/bin/python` in place of the Windows commands. Dependencies must be installed separately; the ZIP does not bundle a Python runtime.

Replace routing_example.csv with your generated molecules, keeping columns:

```csv
id,smiles
molecule_001,CCO
molecule_002,c1ccccc1
```

IDs must be unique and contain only letters, digits, underscores or hyphens, starting with a letter or digit. Examples demonstrate syntax, not guaranteed acceptance.

## Which model and what the output means

Use `models/random_calibrated_router.joblib` by default. It is the first fixed seed (20261022), not a model selected for the best test result. The scaffold model is supplied for comparison; it has its own calibration and training scope. Keep each estimator with its own calibration in its joblib file.

- `use_ml`: read accepted_ml_value_ev, in eV.
- `physical_predict`: ML abstains; accepted_ml_value_ev is null. ml_estimate_ev and intervals are diagnostics. Route this candidate to the physical predictor.
- `input_review`: invalid or unsupported structure; review the molecule first.

Both models predict the GFN2-xTB HOMO-LUMO gap on MMFF94 geometries. They do not predict experimental or ORCA-reference gaps. Training/calibration use part of the 948 successful labels from a 1000-molecule attempt. The narrow source domain is 5-9 heavy atoms; unfamiliar scaffolds and out-of-scope molecules are deliberately deferred. ML does not generate XYZ coordinates.

Nominal normalized 90% intervals achieved mean test coverage 87.7% for random splits and 89.3% for scaffold splits. Coverage is not guaranteed after acceptance filtering or under scaffold shift. Five-seed baseline MAE: random 0.498 +/- 0.026 eV; scaffold 0.517 +/- 0.062 eV (sample SD). The deployed calibrated models use a smaller proper-fit subset; their mean MAEs are 0.519 and 0.545 eV. See the report for full results.

## Reuse in an application

```python
from router import CalibratedRouter
router = CalibratedRouter('models/random_calibrated_router.joblib')
rows = router.route([{'id': 'candidate_001', 'smiles': 'CCO'}])
```

Keep features.py alongside router.py. Route results preserve candidate IDs and order. Local status `abstain` is a routing status, not the shared MolCurator Prediction enum; applications must dispatch the route explicitly. The main package now has its own training implementation. This study uses a different feature layout and calibrated ExtraTrees artifacts; its joblib models are not interchangeable with the main training bundles. Existing agent tools and schemas are unchanged.

The default CLI writes a plan and performs zero electronic calculations. Optional `--run-physical --physical-budget 10 --xyz-dir physical_run/xyz` requires a separately installed, compatible MolCurator package and xTB executable. It executes only budgeted deferred candidates. It does not run ORCA. `execute_routes` also accepts an application-supplied physical callback. The budget counts candidates; backend logs track actual calculation attempts.

## Reports and reproduction

Open Repeated_Splits_Uncertainty_Report.html in any browser; plots are embedded and require no server. Standalone figures are in plots/. All trained models are in models/. The labelled dataset, per-seed metrics, exact split manifest, interval results and routing results are included. previous_experiment/ contains the original 1000-molecule analysis and provenance; its older point-model metrics describe that earlier experiment, not these calibrated artifacts. Raw electronic output directories are not included.

For testing and full analysis dependencies:

```text
python -m pip install -r requirements.txt
python verify_router.py
```

`run_study.py` retrains all five-seed evaluations from the included labelled_dataset.csv and overwrites analysis outputs/models in its folder; run it in a copy if preserving this export. `build_report.py` regenerates plots and HTML. Neither runs xTB or ORCA. Existing audit/verification JSON files document the completed study. PR_VALIDATION.json records checks run on this repository addition. SHA256SUMS.json records artifact checksums.

Study date: 2026-10-22. This folder is a research and regression-test handoff. Only load trusted joblib files; they are Python serialized artifacts. Version-pinned dependencies are provided for model compatibility.

## Run repository tests

From the repository root, install the study test dependencies and run:

```text
python -m pip install -r tests/property_prediction_ml/requirements-test.txt
python -m pytest -q tests/property_prediction_ml
```

The tests use the real saved models and labelled data, verify the exact calibration order statistics and split separation, preserve candidate identity, test unsupported-input handling and abstention, and exercise physical execution budgets with a fake callback. No external executable is called. Test-generated files go to pytest temporary directories. No training or plotting runs during test collection.

The report's `baseline_85pct` models were fitted for evaluation; only the two separately calibrated first-seed models are serialized here. Complete original raw xTB logs remain outside this handoff. Data provenance and known calculation/preparation failures are described in previous_experiment/.

To try the PR before merge: `git fetch origin tools/property-prediction-ml-study` followed by `git switch --track origin/tools/property-prediction-ml-study` in a clean checkout. Main is unaffected until maintainers merge the PR.
