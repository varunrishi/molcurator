# MolCurator API

An HTTP API around the MolCurator agent. It starts agent runs in the background, lets a
client follow them live, and serves their results. The web app in `app/web/` is built on it.

The agent itself is not changed: each run is the existing `molcurator run` command, started
as a separate process. The API reads the files that command writes to `data/runs/<run_id>/`
(trace, dataset, geometries, summary).

| Page | Contents |
|---|---|
| [endpoints.md](endpoints.md) | every endpoint, with request and response examples |
| [deployment.md](deployment.md) | running the server locally, behind a tunnel, or on Kaggle |
| [openapi.json](openapi.json) | machine-readable OpenAPI 3 schema (generated from the code) |

A running server also serves interactive documentation at `/api/docs` (Swagger UI) and
`/api/redoc`.

## Quick start

```bash
scripts/run.sh --install           # first time: install the project (uv sync, or pip install -e .)
scripts/run.sh                     # http://127.0.0.1:8000, prints an API token
```

```bash
TOKEN=...                    # the token printed at startup
curl -s http://127.0.0.1:8000/api/health
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/system
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"config": {"target": {"name": "homo_lumo_gap", "min": 4.0, "max": 4.5},
                  "seeds": ["c1ccc(-c2cccs2)s1"], "decisions": "rules"}}' \
  http://127.0.0.1:8000/api/runs
```

## Conventions

- **Base path:** every endpoint starts with `/api`. The web app is served at `/`.
- **Authentication:** every endpoint except `GET /api/health` needs
  `Authorization: Bearer <token>`. The token comes from `MOLCURATOR_API_TOKEN`; if it is not
  set, the server makes a new one at each start and prints it. `MOLCURATOR_NO_AUTH=1` turns
  authentication off (only for a machine nobody else can reach).
- **CORS:** allowed for every origin by default (`MOLCURATOR_CORS_ORIGINS`), so the web app can
  be opened from another address. The token, not cookies, protects the API.
- **Units:** property values are in the target's units (`target.units`, e.g. eV for
  `homo_lumo_gap`, Eh for `energy`, debye for `dipole_moment`).
- **Ids:** run and molecule ids match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$`.
- **Errors:** `{"detail": "<message>"}`, or for a config that cannot run
  `{"detail": {"message": "...", "problems": ["...", "..."]}}`.

| Status | Meaning |
|---|---|
| 400 | a malformed id |
| 401 | missing or wrong token |
| 404 | no such run, file or geometry |
| 409 | not possible in the run's current state (already running, run limit reached, not resumable) |
| 422 | invalid config, or the server cannot run it (e.g. ORCA missing for QM or for a target only ORCA computes) |

Per-molecule failures are never HTTP errors: they are molecules with `status: "failed"` and an
`error` text.

## Following a run

A run takes minutes to hours, so `POST /api/runs` returns at once (`202`) and the client polls:

```
POST /api/runs                       -> {"run_id": "20261022-070056-1a2b", ...}
GET  /api/runs/<id>?events_since=0   -> status, progress, budgets + all events so far, "events_next": 12
GET  /api/runs/<id>?events_since=12  -> the same, + only the events after the first 12
...                                     until "status" is no longer starting/running/stopping
GET  /api/runs/<id>/molecules        -> after steps that changed molecules, and at the end
```

One request per poll keeps request counts low (the free ngrok plan allows 20,000 a month).
Server-Sent Events are not used because some tunnels (Cloudflare quick tunnels) do not
support them.

An event is written when a step **finishes**, never when it starts, so the step in progress is
reported separately as `current.node` (derived from the graph order).

## Run status

| `status` | Meaning | Can resume? |
|---|---|---|
| `starting` | the process is starting and has not created its folder yet | no |
| `running` | the agent is working | no |
| `stopping` | a stop was requested; the process ends within about 10 s | no |
| `finished` | the summary was written; `stop_reason` says why it ended | no |
| `failed` | a whole step failed (`stop_reason: "error"`, see `error`), or the process died before creating its folder | no |
| `interrupted` | stopped before finishing (stop request, killed process, server restart while starting) | yes, if it has a checkpoint |
| `unknown` | started outside the API (e.g. `molcurator run` in a terminal) and not finished: it may still be running | yes, with care |

`stop_reason` is one of `target_dataset_size`, `max_rounds`, `max_qm_calls`, `max_wall_time`,
`llm` (the LLM decided to stop) or `error`.

## How far to trust a value

Each molecule has values at up to three levels. `best_value` / `best_level` is the most
accurate one it has (QM, else PREDICT, else ML), which is also what CURATE uses.

| Level | Method | Caution |
|---|---|---|
| `qm` | DFT with ORCA (e.g. B3LYP/def2-SVP) | the level a target window is meant for |
| `xtb` | PREDICT on an MMFF94 geometry: GFN2-xTB (tblite) where xTB can give the property, else B97-3c through ORCA; the run's `predict_level` says which | for `homo_lumo_gap`, raw xTB gaps sit well below DFT gaps; `configs/homo_lumo.yaml` corrects them to DFT-like values with a linear fit (60 xTB/B3LYP/def2-SVP pairs, residual SD 0.455 eV), and `xtb_raw` keeps the uncorrected value |
| `ml` | model trained on PREDICT values | the README reports a test MAE of about 0.5 eV (HOMO–LUMO gap); a candidate to check, not a result |

`validated: true` only when QM confirmed the molecule.

## What the server can do

`GET /api/system` reports what is installed and what this version supports. In this version:

- targets: every single-number property the tools compute (`energy`, `homo_lumo_gap`,
  `dipole_moment`, `polarizability`, `g_tensor`, `s1_energy`, `t1_energy`, `s1_t1_gap`,
  `s0_t1_gap`, `ionization_potential`, `electron_affinity`, `thermochemistry`); those xTB
  cannot give (e.g. `s1_t1_gap`) need ORCA for PREDICT;
- generator: `stoned_selfies` only;
- QM backend: `orca` only (PySCF is not built), and only if ORCA is found;
- decisions: `rules`, or `llm` when `ANTHROPIC_API_KEY` is set on the server;
- the agent view's prompt-to-run assistant (`POST /api/assistant/plan`) when `ANTHROPIC_API_KEY` is set;
- no human approval before QM yet.

xTB is available when tblite imports (else through ORCA's built-in xTB). "Found" for ORCA means
an executable file (`ORCA_BIN`, `OPI_ORCA`, OPI's config file or `PATH`); it does not prove
ORCA runs (licence, Open MPI).

## Server settings

Environment variables, or the repo's `.env` file (environment wins):

| Variable | Default | Meaning |
|---|---|---|
| `MOLCURATOR_API_TOKEN` | new random token at each start | API token |
| `MOLCURATOR_NO_AUTH` | `0` | `1` disables authentication |
| `MOLCURATOR_HOST`, `MOLCURATOR_PORT` | `127.0.0.1`, `8000` | address `scripts/run.sh` listens on |
| `MOLCURATOR_RUNS_ROOT` | `data/runs` | where run folders go |
| `MOLCURATOR_MAX_RUNS` | `1` | runs allowed at the same time |
| `MOLCURATOR_CORS_ORIGINS` | `*` | comma-separated allowed origins |
| `MOLCURATOR_WEB_DIR` | `app/web` | web app served at `/` |
| `MOLCURATOR_REPO_URL` | `https://github.com/varunrishi/molcurator` | "Source code" link |
| `ORCA_BIN`, `OPENMPI_HOME`, `ANTHROPIC_API_KEY`, `LLM_MODEL` | — | read by the agent, as without the API; `ANTHROPIC_API_KEY` also enables the agent view |

## Files kept by the API

For runs it starts, the API keeps `<runs_root>/.api/<run_id>.json` (process id, command,
exit code, whether a stop was requested), `<run_id>.log` (everything the agent printed) and
`<run_id>.config.yaml` (the config it was started with). Runs keep going if the API server
restarts, and their status stays correct.
