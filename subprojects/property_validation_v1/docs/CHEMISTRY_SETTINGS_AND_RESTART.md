# Chemistry settings and calculation restart

This follow-up to integration PR 7 preserves the public PREDICT and VALIDATE
signatures and result schemas. It adds validated configuration, durable execution
records, and reuse of completed successful electronic calculations. The default
geometry policy remains MMFF94 conformer optimization, lowest converged minimum,
then xTB or ORCA single point. No electronic geometry optimization is added.

## Configure chemistry

From the repository root:

```bash
cp subprojects/property_validation_v1/config/chemistry.example.json chemistry.json
export MOLCURATOR_CHEM_CONFIG="$PWD/chemistry.json"
uv run --no-sync python scripts/check_property_tools.py --backend all
```

Alternatively set `MOLCURATOR_CHEM_CONFIG=/absolute/path/to/chemistry.json` in
the repository `.env`. The same settings work for the agent, direct Python
calls and smoke checks; there is no separate installation. Direct calls read
`.env` in their current working directory. Exported nonempty settings win over
`.env`. A relative config path is resolved from the current working directory.

Unknown keys, invalid ranges and nonfinite values are rejected. Edit the JSON
file between calls, not while a batch is running. Configuration is loaded for
each candidate; keep it stable for a batch to ensure a common protocol.

| JSON key | Default | Meaning |
| --- | --- | --- |
| `nconfs` | 30 | Requested ETKDGv3 conformers, integer from 1 to 10000 |
| `random_seed` | 42 | Reproducible integer seed, 0 to 2147483647 |
| `mmff_max_iterations` | 500 | Maximum minimization iterations per conformer |
| `mmff_force_tolerance` | 0.0001 | Positive force convergence tolerance passed to RDKit Minimize |
| `mmff_energy_tolerance` | 0.000001 | Positive energy convergence tolerance passed to RDKit Minimize |
| `temperature_k` | 298.15 | Temperature for sampled FF Boltzmann population |
| `rms_cutoff_angstrom` | 0.25 | Heavy-atom RMSD threshold for unique minima |
| `orca_nprocs` | 1 | ORCA PAL process count; allocate these CPUs in the scheduler |
| `orca_maxcore_mb` | 2000 | ORCA maxcore per process in MB, not total job memory |
| `timeout_s` | 600 | Positive wall time limit per external invocation |
| `cache_enabled` | true | Reuse validated complete successes; false forces fresh calculations |
| `cache_epoch` | `"1"` | User-controlled cache invalidation tag for runtime/environment changes |

`MOLCURATOR_QC_TIMEOUT_S`, when nonempty, overrides `timeout_s` in JSON.
An existing `.env` made from the earlier example may set it to 600; remove or
empty that line if you want the JSON timeout to apply. `XTB_BIN` and `ORCA_BIN`
are still configured through environment/`.env`, with executable fallback on
PATH. Functional and basis remain in MolCurator's `QMSettings`, not this JSON.
Charge 0, singlet/closed shell, GFN2 and the single-point geometry policy stay fixed.

The minimizer now visits each embedded conformer with MMFF94 and the explicit
iteration/force/energy settings. Only converged finite minima are ranked. The
geometry report records resolved seed, requested count, tolerances, iterations,
temperature, clustering cutoff, selected energy and sampled population.

## Restart without repeating valid electronic work

Call the same public functions again with the same candidate IDs and output
directory. Retain the complete `calculations` directories. PREDICT recomputes
the inexpensive deterministic FF preparation, then checks the xTB cache.
VALIDATE checks the ORCA cache for the supplied geometry and configured method.
Failed or interrupted calculations are run again; complete matches are reused.
There are no retries within a single invocation.

```python
from pathlib import Path
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate
from molcurator.schemas import Status

# Reuse this same directory on restart; do not require exist_ok=False here.
run_dir = Path("data/runs/generated-001")
predictions = predict(candidates, target, run_dir / "xyz")
selected = [p for p in predictions if p.status is Status.ok]
results = validate(selected, target, qm)
```

For the maintained one-molecule smoke check, use a new directory initially:

```bash
uv run --no-sync python scripts/check_property_tools.py \
  --backend all --smoke --out data/runs/tool-check-001

# Explicitly permit restarting the existing smoke directory:
uv run --no-sync python scripts/check_property_tools.py \
  --backend all --smoke --resume --out data/runs/tool-check-001
```

Both commands run on a compute allocation. Smoke JSON reports cache hits and
electronic calls for the current invocation. An entirely cached smoke does not
claim that it tested the executable runtime again (`runtime_tested` is false).
Do not combine cache restart with the earlier example runner's unconditional
`mkdir(exist_ok=False)`; that guard deliberately rejects existing runs.

## What makes a cache match

Reuse requires the same internal policy version, RDKit version, candidate
identity/context, exact calculation input bytes (including XYZ), command arguments,
all resolved chemistry settings, executable absolute path and SHA256, and selected
runtime environment values (`PATH`, library paths and loaded module names).
Changing functional, basis, geometry, seed, resource count, timeout or cache epoch
invalidates a match, even when the resulting numerical answer might be unchanged.

The success manifest is published atomically only after a completed parsed result
and durable successful attempt record. On reuse, the original log hash and input
bytes must still match, the parser must accept the log again, and the parsed finite
value must equal the saved value. Corrupt, truncated or incomplete artifacts are
not accepted as cached results. A missing executable also prevents cache reuse.

Program version is extracted from the actual xTB/ORCA output when available; no
additional program invocation is made just to probe a version. Missing versions
are recorded as null with `version_status=not_reported`. Executable content is
fingerprinted even when no version banner is present. Dynamic libraries and
external installation data are not all content-hashed: change `cache_epoch` after
such runtime changes to force recalculation. Successful reuse is not a new
independent runtime test. Identical molecules under different IDs/directories
are not deduplicated across the run.

## Calculation records and counts

```text
calculations/<candidate_id>/<xtb-or-orca>/
  attempt.json                     latest invocation summary
  cache.json                       latest reusable completed success
  xtb.out or orca.out               convenient latest output copy
  attempts/<unique-attempt-id>/
    attempt.json                   durable event and resolved recipe
    process.json                   actual launch, PID, exit and timeout state
    initial.xyz or geometry.xyz     retained original inputs
    gap.inp                        ORCA input, when applicable
    xtb.out or orca.out             original process output
```

Each invocation has an isolated process working directory. Records contain UTC
start/end timestamps, duration, timeout limit, timeout flag, PID/return code when
launched, executable fingerprint, program version/status, input hashes, settings,
result/error, and cache source reference for reuse events. No API credentials are
stored; the recipe records only the named chemistry/runtime values.

`electronic_calls_attempted=1` means an external process was created, whether it
succeeded, failed, timed out, or produced unparsable output. A missing executable
or spawn error counts zero. A cache hit also counts zero. ORCA additionally exposes
`qm_calls_attempted` for compatibility. Rejections before electronic execution
(for example invalid SMILES or a failed input prediction) are returned as failed
candidate results but are not electronic attempts. A cached success does not erase
earlier failures; use the durable per-attempt records for cumulative counts.

```bash
uv run --no-sync python scripts/summarize_property_run.py data/runs/tool-check-001
uv run --no-sync python scripts/summarize_property_run.py \
  data/runs/tool-check-001 --json > run-attempts.json
```

The summary reports launched calls per backend, cache events, failures, total
recorded process runtime, running/interrupted events and malformed record errors.
It scans durable records, not the convenient latest summaries, so it does not
double count them. It reads process state for interrupted events when available.
The orchestrator still owns its total budget and should reconcile against these
records; this PR does not change graph budget decisions.

## Limits and operational precautions

- Restart means rerunning tool calls and reusing valid completed results. It is
  not continuation of an interrupted xTB/ORCA internal wavefunction or optimizer.
- Incomplete events remain `started`; they may be running or interrupted. The
  summary does not assume a remote PID is alive. Hard-killed processes may have
  incomplete duration/version data. Do not restart while the original job runs.
- Use one writer per candidate/output directory. Isolated execution directories
  protect calculations, but there is no distributed lock or scheduler; simultaneous
  callers may duplicate work and latest-summary views can race.
- The timeout kills the process group on Linux. Windows terminates the direct
  child; full Windows MPI child cleanup is not guaranteed. Actual MPI/module
  compatibility must be checked on the target cluster.
- ORCA maxcore is per process; reserve additional scheduler memory beyond the
  nominal nprocs times maxcore. This change does not allocate cluster resources.
- Outputs are retained for provenance and can grow; no automatic deletion policy
  is applied. Keep the original logs and inputs if cache reuse is desired.

## Validation

All 75 repository and subproject tests pass in the local test environment.
Tests exercise real local subprocesses emitting controlled output, process
timeout and failure accounting, cache reuse, changed inputs/settings/executable
identity, corrupted and interrupted artifacts, configured RDKit conformer settings,
ORCA input resources and the public mixed-result workflow. These subprocess tests
do not constitute real xTB/ORCA chemistry validation; a cluster smoke test remains
required for the installation and configured MPI resources.
