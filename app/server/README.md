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
| `settings.py` | settings from environment variables / `.env` |

## Install

The server needs the MolCurator package plus two packages of its own:

```bash
scripts/run.sh --install                                   # into .venv if present, else python3
# or by hand:
pip install -r app/server/requirements.txt              # fastapi, uvicorn
pip install -e .                                     # molcurator (full dependencies)
```

For a quick install without PyTorch (e.g. on Kaggle), use
`app/server/requirements-molcurator-light.txt` and then `pip install --no-deps -e .`; it lists the
packages the code actually imports.

## Settings

Environment variables or the repo's `.env`; the full table is in
[`docs/api/README.md`](../../docs/api/README.md#server-settings). The important ones:

- `MOLCURATOR_API_TOKEN`: the API token. If unset, a new one is printed at each start.
- `XTB_BIN` (and `ORCA_BIN` for QM): as for the agent without the API.
- `MOLCURATOR_MAX_RUNS`: how many runs may run at once (default 1).

## Tests

The server's tests are in `tests/server/`, next to the agent's tests, so a plain `pytest` at
the repository root runs them too. Without the server's packages they are skipped.

```bash
pip install -r app/server/requirements-dev.txt          # fastapi, uvicorn, pytest, httpx
python -m pytest tests/server                           # fake chemistry, no xTB needed (a few seconds)
MOLCURATOR_TEST_XTB=$(which xtb) python -m pytest tests/server/test_real_xtb.py   # one real xTB run
```

The tests run the real agent (graph, trace, checkpoints, CURATE) with the repo's fake tools
(`tests/agent/fakes.py`) through `tests/server/fake_agent.py`.

## Known limits

- Stopping: the agent does not always react to Ctrl-C during PREDICT (RDKit handles the
  interrupt itself during conformer embedding and returns normally), so a stop is followed
  by a kill after 10 s. Finished steps are safe in the checkpoint; the interrupted step runs
  again on resume.
- Runs started outside the API (`molcurator run` in a terminal) are listed with status
  `unknown` until they finish, since the server cannot tell whether their process is alive.
- Process tracking uses POSIX process groups and `/proc`: Linux and macOS, not Windows.
