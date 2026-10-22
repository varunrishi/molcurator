# MolCurator property prediction components

This isolated package imports the team's shared `molcurator.schemas` and leaves root tools, agent code, configuration and dependencies untouched. Focused tool PRs add individual modules; see `docs/` for the modules included in this checkout. The existing comprehensive reference branch remains `codex/calibrated-screening-v1`.

From this subproject directory, with Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e ../..
python -m pip install -e '.[test]'
python -m pytest -q tests
```

The first installation exposes shared contracts without installing the full agent stack. All contribution files stay inside this folder. Physics tools require external executables and allocated compute resources; offline tests do not establish chemistry accuracy. The agent owns generation, backend choice, target selection, cumulative budgets and dataset curation.

Each focused branch starts at shared main `2e54567`. They include identical minimal package/geometry/parser support so each is testable independently; these common files should merge identically. The broad API, calibration campaigns, plots, report and other experiments remain on the reference branch for later review.
