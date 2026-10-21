# Batch prediction reports and SLURM jobs

This follow-up to PR 9 adds the installed `molcurator-properties` command.
The agent's existing predict/validate APIs and the MMFF94 single-point chemistry
policy remain unchanged. Batch mode uses those public APIs, configuration and
validated restart caches. It does not require an LLM.

## Install

From the repository root on this branch, or after its dependencies are merged:

```bash
uv sync
uv run --no-sync molcurator-properties --help
```

Plots are off by default. CSV, JSON and Markdown do not require matplotlib.
Enable plots explicitly with `--plots`; install `uv sync --extra reports` first.
The `reports` extra installs matplotlib for headless PNG generation. Root package
installation includes the CLI and chemistry implementation. For an existing
compatible environment, `python -m pip install -e '.[reports]'` is an alternative.
Python 3.11+ is required. The full project's agent/ML dependencies and native
package support still apply. xTB and licensed ORCA are separate executables.

If this environment previously installed the older isolated subproject as
`molcurator-property-validation`, remove that distribution before installing the
root package. It exposes the same namespace/command and an old editable checkout
can shadow the new modules:

```bash
# Only needed when migrating an environment with the old isolated installation.
uv pip uninstall molcurator-property-validation
uv sync --extra reports --reinstall-package molcurator
```

Use the root installation for this integration; do not install both package
distributions into the same environment. A fresh root environment avoids the conflict.

When using a minimal compatible environment, the module form is equivalent:

```bash
python -m molcurator_property_validation.batch --help
```

Set `XTB_BIN`, optional `ORCA_BIN`, and `MOLCURATOR_CHEM_CONFIG` as described in
[chemistry settings and restart](CHEMISTRY_SETTINGS_AND_RESTART.md). Exported
settings override `.env`. Batch mode freezes resolved chemistry settings for the
invocation; edits made during a batch apply only to subsequent calls/invocations.

## Input formats

CSV requires unique `id` and nonempty `smiles` columns:

```csv
id,smiles,parent_smiles,round,generator
mol001,CCO,CC,1,my_generator
mol002,CCCC,CCC,1,my_generator
mol003,c1ccccc1,c1ccccc1,1,my_generator
```

Optional provenance columns are `parent_smiles`, `round` and `generator`; defaults
are the input SMILES, round 1 and `batch_input`. IDs use letters, digits, underscores
or hyphens and must start with a letter or digit. Quote CSV fields containing commas.
Malformed rows, duplicate IDs and invalid provenance are rejected before chemistry.
Invalid chemical SMILES remain candidate failures rather than dropping the row.

SMILES text accepts one SMILES and optional ID per line:

```text
# generated examples
CCO ethanol
CCCC butane
c1ccccc1
```

Blank lines and full-line comments are skipped. IDs are generated as `mol000001`
etc. for unnamed rows using their position in the parsed molecule list. File suffix
`.csv` selects CSV; other suffixes select SMILES text. Override with `--format csv`
or `--format smi`. The batch preserves input order and identity.

## Run on a compute node

Start with xTB only:

```bash
uv run --no-sync molcurator-properties run generated.csv \
  --out data/runs/generated-001
```

Add ORCA validation:

```bash
uv run --no-sync molcurator-properties run generated.csv \
  --out data/runs/generated-orca-001 --orca \
  --functional B3LYP --basis def2-SVP --orca-limit 5
```

All successful xTB predictions are eligible by default. Optional `--min-gap` and
`--max-gap` filter the **raw xTB gap in eV** before ORCA selection. Molecules are
selected in input order, not ranked by predicted quality. `--orca-limit` caps
selected inputs for this invocation, including cached results. It is not a
cumulative budget or a guarantee of that many fresh ORCA launches. The default
limit is unlimited; start with a small set. `--orca-limit 0` performs no validation.
An xTB failure never reaches ORCA. Unselected entries retain explicit reasons.

CSV/JSON/Markdown are produced by default without loading matplotlib. Use `--plots`
for PNGs. `--no-plots` remains a compatibility alias for the default. Missing plotting
dependencies are reported before launching calculations when plots are requested.

## Restart and checkpoints

```bash
uv run --no-sync molcurator-properties run generated.csv \
  --out data/runs/generated-001 --resume
```

Keep the input/provenance identical and retain the same output path. Reusing an
existing output without `--resume` is refused. A normalized input fingerprint
prevents mixing a changed molecule list into an existing run. Keep the same ORCA
and selection flags if you want the same workflow on restart. Changed chemistry
settings or QM methods trigger cache revalidation/recalculation under PR 9 rules.

The CLI checkpoints after each prediction and validation step. It reruns tool calls
on restart and reuses matching successful electronic artifacts; it does not trust
a prior result merely because its row was marked successful. Earlier result snapshots
are retained in `history/`. The current results describe the latest invocation,
while calculation counts include all retained attempts. Geometry preparation is
recomputed; cached electronic calculations do not run again.

An OS advisory lock prevents concurrent CLI writers to the same run directory
where the filesystem supports that locking. The OS releases it when the process
exits, so a leftover `.run.lock` file does not need removal. Do not manually bypass
an active lock or run direct API writers against the same directory concurrently.

## Reports and outputs

```text
data/runs/generated-001/
  results.json             current checkpoint, inputs, settings and result rows
  summary.csv              gaps, statuses, errors, provenance and geometry metadata
  report.md                readable report with linked figures
  attempt_summary.json     cumulative launches, cache hits, runtimes and records
  csv_schema.json          stable CSV version, field list, units and missing-value policy
  plots/                   created only when --plots is explicitly enabled
    gaps.png               current raw xTB and available ORCA values
    status.png             successful, failed and uncalculated/pending candidates
    execution.png          cumulative process launches, cache reuse and runtimes
    conformers.png         unique FF minima and selected FF population estimates
  history/                 snapshots from previous batch invocations
  xyz/                     selected geometries and retained calculation artifacts
```

CSV fields include candidate ID, SMILES/provenance, each backend's status/value/error,
method, XYZ path, FF energy, sampled Boltzmann weight, temperature, unique conformers,
and cumulative per-candidate launches/cache hits/runtime. CSV schema v2 separates
`orca_status` from `orca_selection` and adds `failure_stage`. Cumulative columns
are explicitly named `xtb_calls_total`, `orca_calls_total`, `cache_hits_total` and
`runtime_s_total`; they replace the older ambiguous count names. Missing properties are blank,
not zero. The report does not fit a calibration or claim experimental accuracy.
Plots label current results separately from cumulative history. An all-failed batch
still produces a report and empty-data plots with explicit explanations.

Regenerate reports without running chemistry:

```bash
uv run --no-sync molcurator-properties report data/runs/generated-001
# Explicitly regenerate figures:
uv run --no-sync molcurator-properties report data/runs/generated-001 --plots
```

Exit codes: 0 for a completed batch with no molecule failures, 1 for molecule/runtime
failures, 2 for invalid input/configuration or command errors, and 130 for a handled
keyboard interruption. Reports/checkpoints remain available after mixed failures.
A report-only exit of 0 means generation succeeded, not that the original chemistry
had no failures. Inspect run status and any record warnings. An abruptly killed job
may need report regeneration after restart.

## Prepare a SLURM job

Copy and edit `config/slurm.example.json` in this subproject. All paths inside the
JSON refer to the **Linux cluster**, even if the script is generated on Windows.
Use absolute POSIX paths for project, input, output, chemistry config and binaries.

```bash
cp subprojects/property_validation_v1/config/slurm.example.json slurm.json
uv run --no-sync molcurator-properties slurm \
  --config slurm.json --script jobs/generated-001.sbatch
```

Edit the placeholder username, group, executable paths and partition first. Optional
keys include `account`, `qos`, `modules`, `module_init`, `orca_bin`, `orca`, `orca_limit`, `min_gap`,
`max_gap`, `functional`, `basis`, `resume` and `plots`. `plots` defaults to false
and adds `--plots` to the generated command only when explicitly true. Unknown keys and malformed
resource/directive values are rejected. The Python executable defaults to
`.venv/bin/python` under `project_dir`. Install the environment with reports on the
cluster before submitting. Module loading assumes the cluster exposes its `module`
command in batch shells. If needed, set `module_init` to the absolute path of the
site-provided initialization script, such as `/etc/profile.d/modules.sh`; the
generated script sources that file before loading modules. Use a trusted site file.

Generation does not submit work. Review the generated script, then on the cluster:

```bash
sbatch jobs/generated-001.sbatch
```

Or explicitly generate and submit in one command using a new script filename:

```bash
uv run --no-sync molcurator-properties slurm \
  --config slurm.json --script jobs/generated-002.sbatch --submit
```

The explicit submission uses `sbatch --parsable` and writes a submission receipt
beside the script containing the job ID, config and script path. Existing script
files are not overwritten. If the scheduler response is ambiguous, inspect the
scheduler before trying again. SLURM logs use `molcurator-<jobid>.out` in the
submission working directory. No polling, cancellation or remote login is automated.

This version runs one sequential batch in one single-node job, not a job array.
`cpus_per_task` supports ORCA PAL processes; xTB and FF steps remain single-threaded.
Set `orca_nprocs` in chemistry settings no higher than allocated CPUs. ORCA maxcore
is **per process**; reserve additional memory beyond nprocs times maxcore. Batch mode
checks CPU count and nominal memory against SLURM environment values before chemistry.
Keep the job script outside the batch output directory: creating a script inside it
would create the output directory before the first run, which is deliberately refused.

For restart jobs, set `resume: true` and keep input/output paths unchanged. Confirm
the previous job has stopped. Cluster-specific MPI, module and filesystem locking
behavior still requires a real cluster test.

## Local evidence

The complete automated suite covers CSV/SMILES parsing, mixed failures, checkpoints,
restart input guards, selection/limits, locking, all-failed reports, generated plots,
SLURM directive/path validation and explicit mocked submission. A real local xTB CSV
batch calculated ethanol, butane and benzene, preserved an invalid input failure,
generated reports/figures, and reused all three successful results on restart with
zero new electronic launches. No live SLURM or ORCA execution is claimed by these tests.


## Independent modules

- `batch.py`: CLI dispatch and compatibility facade.
- `batch_inputs.py`: input parsing and identity/provenance validation.
- `batch_runner.py`: checkpointed execution with injectable prediction/validation functions.
- `batch_runtime.py`: run locks and allocation checks.
- `fileio.py`: platform paths and atomic JSON with no chemistry/plotting dependency.
- `report_tables.py`: normalized CSV rows, stable headers and CSV schema metadata.
- `reporting.py`: report assembly and cumulative summaries; no plotting imports by default.
- `plotting.py`: explicitly enabled, headless matplotlib rendering.
- `slurm.py`: validated job generation and opt-in submission.

Report regeneration and CSV export can run independently of calculations. Plotting
is a separate optional layer. The public MolCurator tool signatures are unchanged.
The local validation report is in [reports/local_xtb_validation_20261021](../reports/local_xtb_validation_20261021/README.md). Changes are published on the tool branch; main is unchanged.


## Pre-validation: stop the failed molecule before electronic work

The PREDICT adapter checks each molecule before any xTB launch:

1. Parse one connected SMILES and reject unsupported net charges or radical electrons.
2. Generate ETKDG conformers. An empty ensemble reuses an available single geometry, or attempts one ETKDG embedding with random coordinates and the configured seed. This single geometry is still MMFF94 optimized. Failure to obtain any valid geometry ends that molecule's pipeline; embedding exceptions are reported.
3. Optimize with MMFF94. Missing parameters or zero finite, converged minima ends that molecule's pipeline.
4. Select the lowest-energy converged minimum, export XYZ, and verify the file, atom count, element symbols and finite coordinates.
5. Only after these checks may an xTB single point or a verified cache lookup proceed. Successful predictions can be forwarded to ORCA VALIDATE.

A failed molecule returns its original ID with `status=failed`, an error, and no predicted value or XYZ path. It makes **zero new electronic calls**. The remaining molecules continue; an individual preparation failure does not end the entire agent or batch. VALIDATE also rejects failed predictions before ORCA. Old successful attempt logs remain auditable, but stale published XYZ files are removed before retrying preparation.

Each preparation creates `xyz/calculations/<id>/xtb/prevalidation/<event>.json` and updates `prevalidation.json` beside it. These contain status, stage, code, error and whether electronic work was allowed. The preparation record's `electronic_calls_attempted=0` refers to preparation only; actual later launches are counted in calculation attempt records and cumulative summaries.

Machine-readable reasons include `invalid_or_disconnected_structure`, `unsupported_charge`, `unsupported_radical`, `embedding_failed`, `single_geometry_failed`, `no_conformers`, `mmff_parameters_unavailable`, `no_converged_conformers`, `xyz_creation_failed`, `missing_xyz`, `xyz_write_failed`, `missing_xyz_file`, and `invalid_xyz`. Unexpected preparation exceptions use `geometry_preparation_failed`. A successful gate reports `geometry_ready`.

CSV exports include `prevalidation_status`, `prevalidation_stage`, `prevalidation_code`, `prevalidation_error`, `input_formal_charge`, and `input_radical_electrons`. Unknown metadata in older runs is blank. No radical repair, charge neutralization, alternate force field, or automatic infinite retry is performed.

Single-geometry fallback is recorded in `geometry_report.json` as `single_geometry_fallback` and `geometry_source`. Its FF weight of 1 is conditional on one sampled minimum and does not establish conformational certainty. Historical reports describe the earlier stop-on-empty-ensemble policy; this fallback supersedes it.
