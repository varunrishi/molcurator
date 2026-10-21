# Property extraction and validation subproject

All contributed code, tests, scripts, configs, research results and documentation live inside this directory. Files outside `subprojects/property_validation_v1/` match shared main at `686318f` (`v0.1-contract`). No root tool, schema, agent, dependency, README or configuration changes are required.

## Package boundary

The implementation is `molcurator_property_validation`, under this directory's `src/`. It imports the team's existing `molcurator.schemas` and `molcurator.config` as shared contracts. It never overrides `molcurator.tools` or automatically patches the agent. An agent maintainer can explicitly inject these functions when integrating the contribution.

- `src/molcurator_property_validation/tools/`: predict, validate, configured chemistry stage.
- `src/molcurator_property_validation/chem/`: geometry policy, program execution, gap parsing.
- `src/molcurator_property_validation/screening/`: frozen calibrated ranking.
- `src/molcurator_property_validation/visualization/`: optional XYZ viewers.
- `scripts/`, `configs/`, `tests/`: subproject commands, opt-in config, automated checks.
- `research/`: calibration and target-validation campaigns, exported data and reports.
- `workflows/`, `archive_previous/`, `UPSTREAM_README.md`: preserved historical research package.
- `provenance/previous_root_*`: archived earlier manifests/description for provenance only; do not use them as installation instructions.

## Install without changing the main project

From this subproject directory, create a separate Python 3.11+ environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e ../..
python -m pip install -e '.[test,reports,viewers]'
python -m pytest -q tests
```

The first editable install makes the root package's shared contracts importable without pulling its full agent/ML dependencies. The second installs this isolated package and the requested extras. Neither command edits the root project's tracked files. If the root project is already installed in a compatible environment, only the subproject install is needed.

## Agent usage

```python
from molcurator_property_validation.tools.predict import predict
from molcurator_property_validation.tools.validate import validate
from molcurator_property_validation.tools.chemistry import run_chemistry_round
```

The first two retain the team's existing tool signatures and shared result models. The configured stage reads the shared RunConfig, applies calibrated ranking/exploration, enforces a per-round QM reservation, and prepares shared CuratedEntry records. The caller owns graph routing, cumulative budgets, resume and persistent CURATE.

Read [agent usage](docs/AGENT_CHEMISTRY_USAGE.md), [patch notes](PATCHNOTES.md), and [cluster instructions](CLUSTER.md). The supplied stage config is `configs/homo_lumo_calibrated.yaml`. Existing root defaults are untouched.

## Evidence and limitations

The latest pre-isolation suite had 55 passing checks; the relocated suite verifies the same behavior against shared contracts. Real chemistry evidence includes the reported 24-molecule calibration and 60-molecule validation campaign. See [the report](research/property_validation_results/report/REPORT.md). Only one target hit is observed; calibrated ranking is provisional and is not a validated hard rejection policy.

Only connected neutral closed-shell HOMO–LUMO gaps are supported. TADF, PySCF, persistent dataset curation, the full generator/agent loop, and multi-conformer aggregation remain outside this implementation. The imported historical distribution has no explicit license grant; retain attribution and resolve redistribution permissions with the team.
