# Molecular property predictor

This subproject supplies a property-prediction tool for **molecules produced by the team's generator**. Choose xTB, ORCA, or a separately trained molecular ML model. The tool prepares geometry when needed, runs the chosen method, extracts requested properties, and returns ordered records with original IDs, units, method/provenance, and explicit failures.

All implementation, commands, tests and results remain inside `subprojects/property_validation_v1/`. Root files match shared main at `686318f`; shared schemas and RunConfig are imported unchanged. The package is `molcurator_property_validation` and does not override the main agent's tools.

## Backends

| Backend | Input and computation | Properties currently available |
|---|---|---|
| `xtb` | Generated SMILES -> lowest converged FF conformer -> GFN2-xTB optimization | HOMO, LUMO, HOMO–LUMO orbital gap (eV), dipole magnitude (D), where printed |
| `orca` | Supplied XYZ, xTB-refined geometry (default), or explicitly FF-only geometry -> configured ORCA single point | HOMO, LUMO, orbital gap (eV), dipole magnitude (D), where printed |
| `ml` | Generated SMILES -> Morgan fingerprints -> your trained portable ridge model | Properties present in that model; no geometry/QM calls |

Neutral connected closed-shell molecules are supported. TADF, optical excitation/emission energies, charged/open-shell systems and PySCF are not implemented. Missing requested properties are explicit errors; a partial record retains available values. ORCA functionals/basis are configurable. Calibrated gap ranking remains a separate research utility and is not the ML predictor.

## Install independently

From the subproject directory, using Python 3.11+:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e ../..
python -m pip install -e '.[ml,test,reports,viewers]'
python -m pytest -q tests
```

The root editable install makes shared contracts importable without installing the full agent/ML stack. The subproject install supplies this tool. Neither edits tracked root files. Set `XTB_BIN`/`ORCA_BIN` as executable paths, load cluster runtime modules, and run calculations on compute nodes. See [CLUSTER.md](CLUSTER.md).

## Predict generated molecules

Input JSON can be a list or an object with `candidates`:

```json
[{"id":"generated-001","smiles":"CCO"},{"id":"generated-002","smiles":"c1ccccc1"}]
```

From this directory in the installed environment:

```bash
molcurator-properties predict --input examples/generated_molecules.json \
  --output runs/xtb-example --backend xtb --properties homo lumo homo_lumo_gap dipole

molcurator-properties predict --input examples/generated_molecules.json \
  --output runs/orca-example --backend orca --functional B3LYP --basis def2-SVP
```

Each output directory must be new. ORCA defaults to one xTB geometry optimization before its single point, matching the existing research protocol. To run ORCA without xTB, explicitly add `--geometry force_field`. The Python API also accepts supplied XYZ paths. Different geometry policies are recorded and should not be silently mixed in calibration comparisons.

The console command is equivalent to `python -m molcurator_property_validation predict ...`. It writes `predictions.json` incrementally with requested values, units, method, paths, errors and provenance. A partial/failed molecule makes the command exit nonzero. It does not generate molecules, select a target window, submit jobs or curate a dataset.

## Python and agent use

```python
from pathlib import Path
from molcurator.schemas import Candidate
from molcurator_property_validation import PredictorSettings, predict_properties

molecules = [Candidate(id="generated-001", smiles="CCO", parent_smiles="CCO",
                      round=1, generator="team_generator")]
results = predict_properties(
    molecules,
    PredictorSettings(backend="xtb", properties=["homo_lumo_gap", "dipole"]),
    Path("runs/predictions-001"),
)
```

For the team's unchanged single-property PREDICT signature, bind `PropertyPredictor(settings).predict`. The agent chooses the backend, molecules, target, and calculation budget; this tool only predicts properties. See [agent usage](docs/AGENT_CHEMISTRY_USAGE.md).

## Trained ML backend

No pretrained model is bundled. Fit a baseline on your own finite, same-method labels using CSV columns such as `smiles,homo_lumo_gap,method`, or load a previously trained artifact in the supported JSON format:

```bash
molcurator-properties train-ml --input labelled_molecules.csv --output gap-model.json \
  --properties homo_lumo_gap --reference-method 'dft:B3LYP/def2-SVP'
molcurator-properties predict --input examples/generated_molecules.json \
  --output runs/ml-example --backend ml --model gap-model.json
```

The baseline stores Morgan fingerprint settings, ridge coefficients, target units, training identities and declared reference method. It uses portable JSON rather than executable pickle files. It provides **no calibrated uncertainty or validated accuracy claim**. Evaluate on independent molecules, check overlap with held-out sets, and establish applicability before using it for expensive-call selection. Fitting is a separate optional utility, never triggered automatically by prediction.

## Evidence and retained research

All 70 offline tests pass, covering dispatch, parsing, ID/failure preservation, geometry handoff, configuration, model training/loading, CLI use and agent binding. Physics tests simulate external outputs; cluster software compatibility and scientific accuracy require actual calculations. Existing reported calibration/validation results apply to the earlier xTB/B3LYP orbital-gap protocol, not this new ML model or every newly exposed property.

The `research/` data and [report](research/property_validation_results/report/REPORT.md), historical `workflows/`, and optional calibrated chemistry-stage helper remain available. They are supporting utilities, not prerequisites or automatic agent decisions. See [PATCHNOTES.md](PATCHNOTES.md). The imported historical distribution has no explicit license grant; retain attribution and resolve redistribution permissions with the team.
