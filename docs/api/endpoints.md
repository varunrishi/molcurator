# Endpoint reference

All paths start with `/api`. Every endpoint except `GET /api/health` needs
`Authorization: Bearer <token>`. Examples are real responses from a small run (trimmed where marked `…`).

**System**
- [`GET /api/health`](#get-apihealth)
- [`GET /api/system`](#get-apisystem)
- [`GET /api/presets`](#get-apipresets)
- [`GET /api/config/schema`](#get-apiconfigschema)
- [`POST /api/config/validate`](#post-apiconfigvalidate)
- [`POST /api/chem/inspect`](#post-apicheminspect)

**Runs**
- [`POST /api/runs`](#post-apiruns) start a run
- [`GET /api/runs`](#get-apiruns) list runs
- [`GET /api/runs/{run_id}`](#get-apirunsrun_id) status, progress, budgets (+ new events)
- [`GET /api/runs/{run_id}/events`](#get-apirunsrun_idevents) trace events
- [`GET /api/runs/{run_id}/molecules`](#get-apirunsrun_idmolecules) every molecule
- [`GET /api/runs/{run_id}/dataset`](#get-apirunsrun_iddataset) curated dataset
- [`GET /api/runs/{run_id}/molecules/{molecule_id}/xyz`](#get-apirunsrun_idmoleculesmolecule_idxyz) geometry
- [`GET /api/runs/{run_id}/files/{name}`](#get-apirunsrun_idfilesname) download a file
- [`GET /api/runs/{run_id}/archive`](#get-apirunsrun_idarchive) download the whole run
- [`GET /api/runs/{run_id}/log`](#get-apirunsrun_idlog) process output
- [`GET /api/runs/{run_id}/evaluation`](#get-apirunsrun_idevaluation) trajectory evaluation
- [`POST /api/runs/{run_id}/stop`](#post-apirunsrun_idstop)
- [`POST /api/runs/{run_id}/resume`](#post-apirunsrun_idresume)

---

## `GET /api/health`

Is the server up? No token needed, so a client can find out whether it must ask for one.

```json
{"status": "ok", "version": "0.1.0", "auth_required": true, "repo_url": "https://github.com/varunrishi/molcurator"}
```

## `GET /api/system`

External programs found on the server, what this version supports, and the run limit.

```json
{
  "version": "0.1.0",
  "tools": {
    "xtb": {"found": true, "path": "/opt/xtb/bin/xtb"},
    "orca": {"found": false, "path": null},
    "anthropic_key": {"set": false},
    "python": "3.11.17"
  },
  "capabilities": {
    "targets": [
      {"name": "homo_lumo_gap", "label": "HOMO–LUMO gap", "units": "eV", "supported": true, "reason": null},
      {"name": "s1_t1_gap", "label": "S1–T1 gap (TADF)", "units": "eV", "supported": false,
       "reason": "PREDICT and VALIDATE compute only HOMO–LUMO gaps in this version."}
    ],
    "generators": [ … ], "qm_backends": [ … ], "decision_modes": [ … ],
    "qm_approval": false
  },
  "limits": {"max_concurrent_runs": 1, "running": []}
}
```

The API key itself is never returned, only whether it is set.

## `GET /api/presets`

The use-case configs in `configs/*.yaml`, validated, with every default filled in, so a form
can start from them.

```json
[
  {
    "name": "homo_lumo", "file": "configs/homo_lumo.yaml", "supported": true, "reason": null,
    "notes": ["The seed in this preset is a placeholder; replace it with your own molecule."],
    "config": {"target": {"name": "homo_lumo_gap", "min": 3.0, "max": 3.5, "units": "eV"}, "seeds": ["c1csc(-c2cccs2)c1"], … }
  },
  {"name": "tadf", "supported": false, "reason": "Target s1_t1_gap is not supported yet.", … }
]
```

## `GET /api/config/schema`

JSON Schema of a run config (the `RunConfig` model in `src/molcurator/config.py`).

## `POST /api/config/validate`

Checks a config without starting anything.

Request: `{"config": { …run config… }}`. Missing keys get their defaults. Note that
`decisions` defaults to `"llm"` in `RunConfig`; send `"rules"` to run without an LLM.

Response:

| Field | Meaning |
|---|---|
| `valid` | `true` when there are no problems |
| `config` | the normalised config (all defaults filled in, seeds canonicalised), or `null` |
| `problems` | reasons the run cannot start (invalid values, unsupported target, xTB/ORCA/API key missing) |
| `warnings` | things to know that do not block the run |

```json
{
  "valid": false, "config": { … },
  "problems": ["Target 's1_t1_gap' is not supported yet: PREDICT and VALIDATE compute only homo_lumo_gap."],
  "warnings": ["QM is off: curated molecules will be xTB or ML estimates, not QM-confirmed hits."]
}
```

## `POST /api/chem/inspect`

Checks a seed molecule with RDKit, the library the agent uses.

Request: `{"smiles": "C1=CC=CC=C1", "xyz": true}`. With `xyz: true` (default) the response
includes one quick ETKDG + MMFF94 conformer for preview. PREDICT prepares its own geometry
(30 conformers) before xTB.

```json
{"valid": true, "canonical": "c1ccccc1", "heavy_atoms": 6, "formula": "C6H6", "problems": [], "xyz": "12\n\nC 1.38 …"}
```

`problems` lists what the property tools reject: charged molecules, radicals, more than one
fragment.

---

## `POST /api/runs`

Validates the config, checks the server can run it, and starts the agent in the background.

Request:

```json
{
  "config": {
    "target": {"name": "homo_lumo_gap", "min": 3.0, "max": 3.5},
    "seeds": ["c1ccc(-c2cccs2)s1"],
    "generation": {"defaults": {"n_candidates": 24}},
    "predict": {"n_xtb": 24},
    "budget": {"max_rounds": 2, "target_dataset_size": 100},
    "decisions": "rules"
  },
  "run_id": "ui-demo"
}
```

`run_id` is optional (default: UTC time plus a random suffix). The config is the same as a
`configs/*.yaml` file; to turn QM on, add `"qm": {"backend": "orca", "functional": "B3LYP", "basis": "def2-SVP"}`.

Response `202`:

```json
{"run_id": "ui-demo", "status": "running", "warnings": ["QM is off: …", "The screen compares raw GFN2-xTB gaps with this window. …"]}
```

Errors: `422` with `problems` (invalid config, or the server cannot run it), `409` (run id
exists, or `MOLCURATOR_MAX_RUNS` runs are already running).

## `GET /api/runs`

All runs, newest first.

```json
[
  {
    "run_id": "ui-demo", "status": "finished", "resumable": false,
    "started_at": "2026-10-22T07:00:56.207+00:00", "updated_at": "2026-10-22T07:01:10.730+00:00",
    "target": {"name": "homo_lumo_gap", "min": 3.0, "max": 3.5, "units": "eV"},
    "qm_enabled": false, "decisions": "rules", "stop_reason": "max_rounds", "error": null,
    "dataset_size": 9, "rounds_done": 2
  }
]
```

## `GET /api/runs/{run_id}`

Status, progress, round statistics and budget use. Query parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `events_since` | none | also return the trace events from this index on, and `events_next` |
| `compact` | `true` | in those events, replace per-molecule lists by counts |

```json
{
  "run_id": "ui-demo", "status": "finished", "resumable": false, "exit_code": 0,
  "started_at": "2026-10-22T07:00:56.207+00:00", "updated_at": "2026-10-22T07:01:10.730+00:00",
  "running_seconds": 14.5,
  "target": {"name": "homo_lumo_gap", "min": 3.0, "max": 3.5, "units": "eV"},
  "qm_enabled": false, "decisions": "rules",
  "nodes": ["plan_round", "generate", "predict", "train", "ml_predict", "screen", "curate",
            "close_round", "continue_or_stop", "write_summary"],
  "current": {"node": null, "round": 2},
  "last_event": {"node": "write_summary", "round": 2, "status": "ok"},
  "rounds": [
    {"round": 1, "generated": 24, "duplicates": 0, "xtb_runs": 24, "ml_predicted": 0, "unscored": 0,
     "failed": 0, "screened_in": 7, "selected": 0, "qm_calls": 0, "hits": 3},
    {"round": 2, "generated": 24, "duplicates": 1, "xtb_runs": 23, … , "hits": 6}
  ],
  "budget": {"rounds_done": 2, "max_rounds": 2, "qm_calls_used": 0, "max_qm_calls": 20,
             "dataset_size": 9, "target_dataset_size": 100, "running_seconds": 14.5, "max_wall_time": 3600.0},
  "stop_reason": "max_rounds", "error": null, "event_count": 20,
  "files": {"dataset.csv": true, "dataset_ml_only.csv": true, "summary.md": true, "config.yaml": true, "trace.jsonl": true},
  "events": [ … ], "events_next": 20
}
```

- `current.node` is the step in progress while the run is active (`null` otherwise).
- `running_seconds` counts running time only (time spent stopped is excluded, as the agent's
  `max_wall_time` does).
- `budget.qm_calls_used` counts finished rounds.
- A compact event is a trace line ([docs/trace-format.md](../trace-format.md)) where
  `outputs.results` is replaced by `result_counts` (e.g. `{"predicted": 23, "failed": 1}`),
  `inputs.candidate_ids` by `inputs.candidate_count`, and the LLM prompt and raw response are
  dropped.

## `GET /api/runs/{run_id}/events`

Raw trace events, exactly as in `traces/trace.jsonl`. Query: `since` (default 0), `limit`
(default 1000, max 10000), `compact` (default `false`).

```json
{"events": [ … ], "next": 3, "total": 20}
```

## `GET /api/runs/{run_id}/molecules`

Every molecule of the run, rebuilt from the per-molecule results in the trace and joined with
`dataset.csv`.

```json
[
  {
    "id": "r1-c004", "smiles": "c1csc(C2CS2)c1", "round": 1, "status": "curated",
    "xtb": 3.089615033327, "ml": null, "qm": null, "qm_method": null, "error": null,
    "curated": true, "validated": false, "parent": "c1csc(-c2cccs2)c1",
    "best_value": 3.089615033327, "best_level": "xtb", "in_window": true, "has_xyz": true
  },
  {
    "id": "r1-c000", "smiles": "C=C[SH]1C=CC=C1c1cccs1", "round": 1, "status": "screened_out",
    "xtb": 0.33907280861, … , "parent": null, "best_level": "xtb", "in_window": false, "has_xyz": true
  }
]
```

- `status` is the molecule's last status: `generated`, `duplicate`, `predicted`, `ml_predicted`,
  `unscored`, `failed`, `screened_in`, `screened_out`, `selected`, `validated`, `curated`.
- `error` is set for failed molecules and names the step, e.g. `"predict: ValueError: …"`.
- `parent` is known only for curated molecules (the trace does not record it per molecule).
- `in_window` compares `best_value` with the target window, without the screening margin.

## `GET /api/runs/{run_id}/dataset`

`dataset.csv` as JSON rows (numbers as numbers, empty cells as `null`).

```json
[{"id": "r1-c004", "smiles": "c1csc(C2CS2)c1", "xyz_path": "xyz/r1-c004.xyz", "ml": null, "xtb": 3.0896,
  "qm": null, "qm_method": null, "validated": false, "parent": "c1csc(-c2cccs2)c1", "round": 1,
  "generator": "stoned_selfies", "seeds": "c1csc(-c2cccs2)c1"}]
```

## `GET /api/runs/{run_id}/molecules/{molecule_id}/xyz`

The geometry PREDICT selected for the molecule (MMFF94), as XYZ text. `404` if the molecule
had no xTB step.

## `GET /api/runs/{run_id}/files/{name}`

Downloads one file. `name` is one of `dataset.csv`, `dataset_ml_only.csv`, `summary.md`,
`config.yaml`, `trace.jsonl`. `404` if it does not exist yet.

## `GET /api/runs/{run_id}/archive`

The whole run folder as `<run_id>.zip`: dataset, geometries, xTB outputs, models, trace,
summary and checkpoint. Use it to keep results from a temporary machine (e.g. Kaggle).

## `GET /api/runs/{run_id}/log`

Plain text: the last `lines` (default 200, max 5000) lines the agent process printed. Only for
runs started through the API. Useful when a run failed.

## `GET /api/runs/{run_id}/evaluation`

Runs the trajectory evaluator (`src/molcurator/trajectory_evaluation.py`) on the trace and
returns its report: `overall`, `checks` (`tool_correctness`, `ordering`, `budget_adherence`,
`repeated_work`, `failure_handling`), `capabilities` (what could and could not be checked),
`findings` and `summary`. See [docs/agent-trajectory-evaluation.md](../agent-trajectory-evaluation.md).
A pass means the agent behaved correctly, not that target molecules were found.

## `POST /api/runs/{run_id}/stop`

Asks a running run to stop (`202`, `{"status": "stopping"}`). The API sends SIGINT (like Ctrl-C);
if the run has not ended after 10 seconds it is killed, together with the xtb/orca processes it
started. The agent saves a checkpoint after every finished step, so nothing finished is lost;
the step that was in progress runs again on resume. (The agent does not always react to
Ctrl-C in the middle of PREDICT, because RDKit handles the interrupt itself during conformer
embedding and PREDICT then carries on with the next molecule.)

`409` if the run is not running.

## `POST /api/runs/{run_id}/resume`

Continues an interrupted run from its last finished step, with its saved config
(`molcurator run --resume`). `202`, `{"status": "running"}`. `409` if the run is not resumable
or the run limit is reached.
