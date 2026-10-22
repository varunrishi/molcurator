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
- [`POST /api/assistant/plan`](#post-apiassistantplan) prompt → proposed run (Claude)

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

Property programs found on the server, what this version supports, and the run limit.

```json
{
  "version": "0.1.0",
  "tools": {
    "xtb": {"found": true, "via": "tblite", "note": "GFN2-xTB runs in-process through tblite."},
    "orca": {"found": false, "path": null, "source": "PATH"},
    "anthropic_key": {"set": false},
    "python": "3.11.17"
  },
  "capabilities": {
    "targets": [
      {"name": "energy", "label": "Total energy", "units": "Eh", "description": "Total electronic energy (single point).",
       "predict_method": "GFN2-xTB", "needs_orca": false, "supported": true, "reason": null},
      {"name": "homo_lumo_gap", "label": "HOMO–LUMO gap", "units": "eV", "description": "HOMO-LUMO gap; HOMO and LUMO energies in details.",
       "predict_method": "GFN2-xTB", "needs_orca": false, "supported": true, "reason": null},
      {"name": "s1_t1_gap", "label": "S1–T1 gap (TADF)", "units": "eV", "description": "Singlet-triplet gap Delta E_ST = E(S1) - E(T1) from TD-DFT.",
       "predict_method": "B97-3c", "needs_orca": true, "supported": true, "reason": null},
      …
    ],
    "generators": [ … ], "qm_backends": [ … ], "decision_modes": [ … ],
    "qm_approval": false
  },
  "limits": {"max_concurrent_runs": 1, "running": []},
  "assistant": {"available": false, "model": "claude-haiku-4-5"}
}
```

The API key itself is never returned, only whether it is set.

- `tools.xtb`: `via` is `"tblite"` (in-process, the normal case), `"orca"` (tblite cannot be
  imported, so ORCA's built-in xTB is used) or `null` (neither).
- `tools.orca`: looked up as the agent does: `ORCA_BIN`, else `OPI_ORCA`, else `ORCA_PATH` in
  OPI's config file, else `orca` on `PATH`; `source` says which. "Found" means an executable
  file; it does not prove ORCA runs (licence, Open MPI).
- `capabilities.targets`: every single-number property the tools compute
  (`molcurator.chem.properties.SCALAR_PROPERTIES`), with its unit and default PREDICT method.
  Targets with `needs_orca: true` can run only where ORCA is found.

## `GET /api/presets`

The use-case configs in `configs/*.yaml`, validated, with every default filled in, so a form
can start from them.

```json
[
  {
    "name": "homo_lumo", "file": "configs/homo_lumo.yaml", "supported": true, "reason": null,
    "predict_level": {"method": "GFN2-xTB", "basis": null, "label": "GFN2-xTB corrected to DFT-like", "xtb": true,
                      "corrected": true, "correction_fitted_on": "60 xTB/B3LYP/def2-SVP pairs, b3lyp_validation60"},
    "notes": ["The seed in this preset is a placeholder; replace it with your own molecule."],
    "config": {"target": {"name": "homo_lumo_gap", "min": 4.0, "max": 4.5, "units": "eV"}, "seeds": ["c1csc(-c2cccs2)c1"],
               "predict": {"n_xtb": 200, "method": null, "basis": null,
                           "correction": {"slope": 0.6915, "intercept": 3.2347, "residual_sd": 0.455, "xtb_range": [1.02, 8.84], …}}, … }
  },
  {
    "name": "tadf", "predict_level": {"method": "B97-3c", "label": "B97-3c", "xtb": false, "corrected": false, …},
    "notes": ["The seed in this preset is a placeholder; …", "PREDICT runs B97-3c through ORCA, which was not found on this server."], …
  }
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
| `problems` | reasons the run cannot start (invalid values, a property the tools do not compute, a PREDICT level that cannot work, xTB/ORCA/API key missing) |
| `warnings` | things to know that do not block the run |

```json
{
  "valid": false, "config": { … },
  "problems": ["PREDICT runs B97-3c for s1_t1_gap, which needs ORCA, and ORCA was not found on the server (set ORCA_BIN)."],
  "warnings": ["QM is off: curated molecules will be B97-3c or ML estimates, not QM-confirmed hits.",
               "PREDICT runs B97-3c through ORCA: minutes per molecule rather than seconds."]
}
```

## `POST /api/chem/inspect`

Checks a seed molecule with RDKit, the library the agent uses.

Request: `{"smiles": "C1=CC=CC=C1", "xyz": true}`. With `xyz: true` (default) the response
includes one quick ETKDG + MMFF94 conformer for preview. PREDICT prepares its own geometry
(30 MMFF94 conformers by default) before PREDICT.

```json
{"valid": true, "canonical": "c1ccccc1", "heavy_atoms": 6, "formula": "C6H6", "problems": [], "xyz": "12\n\nC 1.38 …"}
```

`problems` lists what the property tools reject: charged molecules, radicals, more than one
fragment.

## `POST /api/assistant/plan`

Turns a plain-language request into a proposed run config with Claude (the web app's agent
view). Available only when `ANTHROPIC_API_KEY` is set on the server (`/api/system` reports
`assistant.available`); otherwise `503`. **Nothing is started**: the client shows the proposal
and starts it with `POST /api/runs`.

Request: `{"prompt": "…", "current": { …config from a previous answer… } | null}`. With
`current`, the prompt changes that proposal (e.g. "use 8 rounds").

Claude only fills a small form (property, window, seed, candidates, rounds, dataset size, time,
QM). The server starts from the preset shipped for that property (`homo_lumo` for
`homo_lumo_gap`, `tadf` for `s1_t1_gap`; for other properties the preset with the same kind of
PREDICT, without the gap correction), then validates and checks it like any config, and checks
the seed with RDKit. The target window and seed are never taken from the preset: if the user did
not give them, they are reported as problems. QM validation is on by default when ORCA is found,
otherwise off with a warning.

```json
{
  "understood": true, "reply": "Here is the run I would set up.", "missing": [],
  "config": { …full run config… },
  "seed": {"valid": true, "canonical": "c1csc(-c2cccs2)c1", "formula": "C8H6S2", "heavy_atoms": 10, "problems": [], "xyz": "…"},
  "problems": [],
  "warnings": ["QM validation is off because ORCA was not found on the server.",
               "The seed SMILES was written by Claude from the name '2,2'-bithiophene'. Check the drawing.", "QM is off: …"],
  "target": {"name": "homo_lumo_gap", "label": "HOMO–LUMO gap", "units": "eV", …},
  "predict_level": {"method": "GFN2-xTB", "label": "GFN2-xTB corrected to DFT-like", "xtb": true, "corrected": true, …},
  "defaults_used": ["dataset size", "time budget", "QM"],
  "ready": true, "model": "claude-haiku-4-5"
}
```

`ready` is true when Claude understood the request and there are no problems. `502` if Claude
could not be reached or its answer could not be used.

---

## `POST /api/runs`

Validates the config, checks the server can run it, and starts the agent in the background.

Request:

```json
{
  "config": {
    "target": {"name": "homo_lumo_gap", "min": 4.0, "max": 4.5},
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
Leave `target.units` out to use the property's own unit. Without `predict.correction`, HOMO–LUMO
gaps are raw GFN2-xTB values (copy the correction from `configs/homo_lumo.yaml` for a DFT-level window).

Response `202`:

```json
{"run_id": "ui-demo", "status": "running", "warnings": ["QM is off: …", "PREDICT compares raw GFN2-xTB gaps with this window. …"]}
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
  "predict_level": {"method": "GFN2-xTB", "label": "GFN2-xTB", "xtb": true, "corrected": false},
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

- `predict_level` is what PREDICT computed in this run, from its saved config: e.g. `"GFN2-xTB"`,
  `"GFN2-xTB corrected to DFT-like"` (with `predict.correction`, as in `configs/homo_lumo.yaml`)
  or `"B97-3c"` (TD-DFT through ORCA for `s1_t1_gap`). PREDICT values are always in the `xtb`
  fields (named as in `dataset.csv`), whatever method ran.
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
    "xtb": 3.089615033327, "xtb_raw": 3.089615033327, "xtb_extrapolated": false,
    "ml": null, "qm": null, "qm_method": null, "error": null, "curated": true, "validated": false, "parent": "c1csc(-c2cccs2)c1",
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
- `xtb` is the PREDICT value the run used. With `predict.correction` it is the DFT-like corrected
  value, `xtb_raw` the value xTB gave, and `xtb_extrapolated` is `true` when `xtb_raw` lies
  outside the range the correction was fitted on. `dataset.csv` stores `xtb_raw` for curated
  molecules; for the others the server recovers it from the run's correction
  (`corrected = slope × raw + intercept`). Without a correction `xtb_raw` equals `xtb`.

A molecule from a run with the correction (`configs/homo_lumo.yaml`):

```json
{"id": "r1-c000", "smiles": "C1=CC1c1cccs1", "round": 1, "status": "screened_out",
 "xtb": 5.195227536284057, "xtb_raw": 2.8351808189212684, "xtb_extrapolated": false, "ml": null, "qm": null, …,
 "best_value": 5.195227536284057, "best_level": "xtb", "in_window": false, "has_xyz": true}
```

## `GET /api/runs/{run_id}/dataset`

`dataset.csv` as JSON rows (numbers as numbers, empty cells as `null`).

```json
[{"id": "r1-c004", "smiles": "c1csc(C2CS2)c1", "xyz_path": "xyz/r1-c004.xyz", "ml": null, "xtb": 3.0896,
  "xtb_raw": 3.0896, "xtb_extrapolated": false, "qm": null, "qm_method": null, "validated": false, "parent": "c1csc(-c2cccs2)c1", "round": 1,
  "generator": "stoned_selfies", "seeds": "c1csc(-c2cccs2)c1"}]
```

## `GET /api/runs/{run_id}/molecules/{molecule_id}/xyz`

The geometry PREDICT selected for the molecule (MMFF94), as XYZ text. `404` if the molecule
had no PREDICT step.

## `GET /api/runs/{run_id}/files/{name}`

Downloads one file. `name` is one of `dataset.csv`, `dataset_ml_only.csv`, `summary.md`,
`config.yaml`, `trace.jsonl`. `404` if it does not exist yet.

## `GET /api/runs/{run_id}/archive`

The whole run folder as `<run_id>.zip`: dataset, geometries, PREDICT records, models, trace,
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
if the run has not ended after 10 seconds it is killed, together with the ORCA processes it
started. The agent saves a checkpoint after every finished step, so nothing finished is lost;
the step that was in progress runs again on resume. (The agent does not always react to
Ctrl-C in the middle of PREDICT, because RDKit handles the interrupt itself during conformer
embedding and PREDICT then carries on with the next molecule.)

`409` if the run is not running.

## `POST /api/runs/{run_id}/resume`

Continues an interrupted run from its last finished step, with its saved config
(`molcurator run --resume`). `202`, `{"status": "running"}`. `409` if the run is not resumable
or the run limit is reached.
