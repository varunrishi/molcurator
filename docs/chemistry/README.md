# MolCurator property prediction components

xTB PREDICT, ORCA VALIDATE and the batch tools, contributed by a_elm. They began as the isolated
subproject `subprojects/property_validation_v1/` and now live in the main package:

| Where | What |
|---|---|
| `src/molcurator/tools/predict.py`, `validate.py` | the PREDICT (GFN2-xTB) and VALIDATE (ORCA) tools the agent calls |
| `src/molcurator/chem/` | conformers and geometry checks, xTB/ORCA execution, settings, restartable tracking |
| `src/molcurator/batch/` | the `molcurator-properties` command: batch runs, reports, SLURM jobs |
| `tests/chemistry/` | their tests (no xTB or ORCA needed) |
| `configs/chemistry.example.json`, `slurm.example.json` | example settings |
| `data/properties/` | the shared property dataset (`PROPERTY_DATA.md`) |
| `research/property_validation/reports/` | the local xTB validation report |

They install and test with the rest of the project (`uv sync`, then `pytest`); see the main README. Physics
tools need the external executables (`XTB_BIN`, `ORCA_BIN` in `.env`) and offline tests do not establish
chemistry accuracy. The agent owns generation, backend choice, target selection, budgets and curation.

Guides in this folder: [PREDICT_XTB](PREDICT_XTB.md), [VALIDATE_ORCA](VALIDATE_ORCA.md),
[CHEMISTRY_SETTINGS_AND_RESTART](CHEMISTRY_SETTINGS_AND_RESTART.md),
[BATCH_REPORTS_AND_SLURM](BATCH_REPORTS_AND_SLURM.md), [MAIN_TOOL_INTEGRATION](MAIN_TOOL_INTEGRATION.md).
The broader reference work (calibration, plots, further experiments) is on the branch
`codex/calibrated-screening-v1`.
