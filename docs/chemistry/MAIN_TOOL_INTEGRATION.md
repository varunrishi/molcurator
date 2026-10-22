# Main tool integration

The ordinary imports used by the agent now delegate to the chemistry implementation:

```python
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate

# predictions = predict(candidates, config.target, run_dir / 'xyz')
# results = validate(selected_predictions, config.target, config.qm)
```

Signatures and shared result models are unchanged. Root setuptools includes the isolated implementation in the normal root installation, so no sys.path manipulation or second subproject installation is required. In an existing compatible environment, run `python -m pip install --no-deps -e .` from the repository root to refresh installation; use the project's normal dependency setup on a fresh machine.

Export XTB_BIN and ORCA_BIN or place executables on PATH and load required cluster runtime modules. PREDICT estimates raw GFN2-xTB HOMO-LUMO gap in eV and returns the selected MMFF94-optimized XYZ. VALIDATE reuses that geometry for one configured ORCA single point per selected molecule. IDs/order, failed records, geometry reports, raw logs and attempt records are retained. The graph owns selection and cumulative budgets.

Scope is neutral closed-shell HOMO-LUMO gaps. PySCF, TADF and ML selection remain separate work. No graph, schema, screening policy or LLM decision changes are included. The agent/orchestrator branch's Toolset.default() already imports these root functions and will use them when both contributions are integrated.

This integration PR includes the implementation from PRs #3 and #4 plus the missing root entry points, packaging and public-import tests. It supersedes separately integrating those implementation-only patches for this use case. Merge through review; no direct changes to main are made.

Tests verify public imports, argument/result delegation, mixed failures, configured ORCA method and geometry reuse. External program output is simulated; actual cluster compatibility still needs real calculations. The root install/wheel check verifies that both package trees are included.

## Automated setup and checks

From the root checkout after this PR is merged (or on this branch):

```bash
bash scripts/setup.sh --no-llm
```

The existing setup creates/refreshes the locked Python environment with uv and finds/installs xTB where supported. It now finishes with the chemistry preflight and exits nonzero if a dependency or required executable is unavailable. ORCA must be installed separately under its license, or loaded through the cluster's modules. Set `XTB_BIN` and `ORCA_BIN` to absolute executable paths in `.env`; existing exported process settings take precedence. Only chemistry path/timeout keys are loaded by the tool; no API key is needed for these calculations.

Recheck without reinstalling or calculating:

```bash
uv run --no-sync python scripts/check_property_tools.py --backend all
# Machine-readable output:
uv run --no-sync python scripts/check_property_tools.py --backend all --json
```

This verifies Python 3.11+, required tool imports, executable resolution and executable permission. Finding a file does not establish that its shared libraries, runtime modules, MPI environment or license work. The output explicitly states that runtime has not been tested. Run `--backend xtb` for xTB-only readiness or `--backend orca` for ORCA-only readiness.

On an allocated compute node, opt into a real one-molecule check:

```bash
uv run --no-sync python scripts/check_property_tools.py \
  --backend all --smoke --out data/runs/tool-check-001
```

Use a new output directory each time. This performs real ethanol geometry preparation, xTB and one ORCA single point, saves raw calculation artifacts plus `preflight-smoke.json`, and exits nonzero on failure. `--backend orca --smoke` uses an explicitly FF-only geometry, not the xTB/B3LYP calibration protocol. No chemistry runs during the default availability check or setup preflight. Use `--env-file` if settings are not in the root `.env`.

The full project's dependency sync includes ML/agent dependencies and PySCF; native-platform package support is still required. This change reports failures rather than claiming it can automatically install licensed ORCA or fix cluster runtime modules.
## Geometry policy (iteration 1)

SMILES -> explicit hydrogens -> 30 ETKDGv3 conformers (seed 42) -> MMFF94
optimization of every conformer (maximum 500 iterations) -> lowest-energy
converged conformer -> GFN2-xTB and/or configured ORCA HOMO-LUMO single point.
No xTB or ORCA geometry optimization is performed. Missing MMFF94 parameters
produce a failed candidate rather than a silent UFF fallback. Charged, radical,
and disconnected structures are unsupported in this iteration.

The geometry report records selected energy in kcal/mol, converged and unique
conformer counts, and estimated Boltzmann population at 298.15 K over unique
sampled minima (0.25 angstrom heavy-atom RMSD clustering). This estimate is
conditional on the sampled force-field ensemble.

Each electronic backend runs once per eligible selected molecule. Conformer
generation and MMFF94 optimizations do not count as electronic calculations.
ORCA validation reuses the selected geometry returned by PREDICT. The ORCA-only
smoke test prepares the MMFF94 geometry directly without requiring xTB.


## Configurable chemistry and restart

See [Chemistry settings and calculation restart](CHEMISTRY_SETTINGS_AND_RESTART.md)
for the follow-up configuration, durable attempt records, cache validation and
`--resume` smoke option. Settings retain the defaults described above but can now
override conformer preparation, MMFF convergence, temperature and ORCA resources.


## Batch command reports and cluster jobs

See [Batch prediction reports and SLURM jobs](BATCH_REPORTS_AND_SLURM.md) for
`molcurator-properties run`, automatic CSV/Markdown/PNG reports, checkpointed
restart and configurable single-job SLURM preparation/submission.
