# MolCurator API server

A small FastAPI server that starts MolCurator agent runs in the background, lets clients follow
them, and serves their results. It also serves the web app (`app/web/`) at `/`.

- Start it: `scripts/run.sh` (`scripts/run.sh --help` for options).
- API reference: [`docs/api/`](../../docs/api/README.md); live docs at `/api/docs` on a running server.

## How it works

The agent is not changed. Each run is the existing `molcurator run` command, started as its
own process, and the server reads what that command writes to `data/runs/<run_id>/`:

```
web app / curl ──HTTP──► FastAPI (routes.py)
                             │ start / stop / resume              │ read
                             ▼                                    ▼
                  run_manager.py: `molcurator run …`   run_files.py: trace.jsonl, dataset.csv,
                  in its own process group             xyz/, summary.md, config.yaml
```

| File | What it does |
|---|---|
| `__init__.py` | marks `app/server` as the Python package `server` (version number) |
| `main.py` | creates the app: routes, CORS, `/api/docs`, the web app at `/` |
| `routes.py` | every endpoint, with the token check |
| `run_manager.py` | starts, stops and resumes run processes; keeps `<runs_root>/.api/` |
| `run_files.py` | turns a run folder into JSON: status, progress, molecules, dataset |
| `capabilities.py` | what this version supports, tool lookup, checks before a run starts |
| `chem.py` | RDKit check and 3D preview of a seed molecule |
| `assistant.py` | prompt → proposed run with Claude (agent view); merged and checked like any config |
| `settings.py` | settings from environment variables / `.env` |

## Install

The server's packages (`fastapi`, `uvicorn`) are ordinary project dependencies in
`pyproject.toml`, so the normal project setup installs them:

```bash
uv sync                      # or scripts/setup.sh, or: pip install -e .
scripts/run.sh --install     # the same, then starts the server
```

On Windows, use the conda environment (`environment.yml`) so tblite is installed; without it
xTB runs through ORCA's built-in xTB. `notebooks/deploy_kaggle.ipynb` installs the project on
Kaggle without pyscf and langchain-openai, which the agent does not need there.

## Settings

Environment variables or the repo's `.env`; the full table is in
[`docs/api/README.md`](../../docs/api/README.md#server-settings). The important ones:

- `MOLCURATOR_API_TOKEN`: the API token. If unset, a new one is printed at each start.
- `ORCA_BIN` (or `OPI_ORCA`, or `orca` on PATH): ORCA 6.1.1+, for QM validation and for targets whose
  PREDICT needs ORCA (e.g. `s1_t1_gap`). xTB needs no setting: it runs in-process through tblite.
- `MOLCURATOR_MAX_RUNS`: how many runs may run at once (default 1).

## Tests

The server's tests are in `tests/server/`, next to the agent's tests, so a plain `pytest` at
the repository root runs them too. Without the server's packages they are skipped.

```bash
uv sync                                                 # includes the dev group: pytest, httpx
python -m pytest tests/server                           # about 10 s
```

`test_real_xtb.py` makes one small real run with GFN2-xTB through tblite (skipped where tblite
cannot be imported); the other tests use fake chemistry. They run the real agent (graph, trace, checkpoints, CURATE) with the repo's fake tools
(`tests/agent/fakes.py`) through `tests/server/fake_agent.py`.

## Known limits

- Stopping: the agent does not always react to Ctrl-C during PREDICT (RDKit handles the
  interrupt itself during conformer embedding and returns normally), so a stop is followed
  by a kill after 10 s. Finished steps are safe in the checkpoint; the interrupted step runs
  again on resume.
- Runs started outside the API (`molcurator run` in a terminal) are listed with status
  `unknown` until they finish, since the server cannot tell whether their process is alive.
- Process tracking uses POSIX process groups and `/proc`: Linux and macOS, not Windows.
