"""Shared fixtures: an API app wired to a temporary runs folder and the fake agent."""
import stat
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parents[1]  # app/server
REPO = SERVER.parents[1]
sys.path.insert(0, str(SERVER))

from molcurator_api.main import create_app  # noqa: E402
from molcurator_api.settings import Settings  # noqa: E402

TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    fake_xtb = tmp_path / "bin" / "xtb"  # preflight only checks that xTB exists; the fake agent never calls it
    fake_xtb.parent.mkdir()
    fake_xtb.write_text("#!/bin/sh\nexit 0\n")
    fake_xtb.chmod(fake_xtb.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("XTB_BIN", str(fake_xtb))
    monkeypatch.delenv("ORCA_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Settings(repo=REPO, runs_root=tmp_path / "runs", web_dir=REPO / "app" / "web", api_token=TOKEN,
                    token_was_generated=False, max_runs=1, cors_origins=["*"],
                    repo_url="https://example.invalid/molcurator",
                    agent_cmd=[sys.executable, str(SERVER / "tests" / "fake_agent.py")])


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
