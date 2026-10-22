"""Shared fixtures: an API app wired to a temporary runs folder and the fake agent."""
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent  # tests/server
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "app"))  # the `server` package, imported as scripts/run.sh does (--app-dir app)

from server.main import create_app  # noqa: E402
from server.settings import Settings  # noqa: E402

TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    # xTB is found through tblite, a dependency; the fake agent never calls it
    monkeypatch.delenv("ORCA_BIN", raising=False)
    # "no ORCA on this server" whatever this machine has on PATH, so results do not depend on it
    which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "orca" else which(name, *a, **k))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Settings(repo=REPO, runs_root=tmp_path / "runs", web_dir=REPO / "app" / "web", api_token=TOKEN,
                    token_was_generated=False, max_runs=1, cors_origins=["*"],
                    repo_url="https://example.invalid/molcurator",
                    agent_cmd=[sys.executable, str(HERE / "fake_agent.py")])


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def small_config(**changes) -> dict:
    """A tiny HOMO-LUMO run: 6 candidates per round, rules decisions, no QM."""
    config = {"target": {"name": "homo_lumo_gap", "min": 3.0, "max": 3.5}, "seeds": ["c1ccccc1"],
              "generation": {"defaults": {"n_candidates": 6}}, "predict": {"n_xtb": 4},
              "train": {"min_examples": 4}, "budget": {"max_rounds": 2, "target_dataset_size": 1000},
              "decisions": "rules"}
    config.update(changes)
    return config


def wait_for(client: TestClient, run_id: str, statuses: set[str], timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        overview = client.get(f"/api/runs/{run_id}").json()
        if overview["status"] in statuses:
            return overview
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach {statuses}; last: {overview}")
