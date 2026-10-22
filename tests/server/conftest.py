"""Shared fixtures for the API server tests: an app wired to a temporary runs folder and the
fake agent. They need fastapi (a project dependency) and httpx (in the dev group of
pyproject.toml; `uv sync` installs both). Without them these tests are skipped, not failed.
"""
from __future__ import annotations  # annotations stay unevaluated when the server packages are missing

import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent          # tests/server
REPO = HERE.parents[1]
SERVER = REPO / "app" / "server"

try:
    import fastapi  # noqa: F401
    import httpx  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]          # skip this folder: server packages not installed
else:
    sys.path.insert(0, str(SERVER.parent))       # app/: makes the `server` package importable
    from fastapi.testclient import TestClient
    from server.main import create_app
    from server.settings import Settings

    from tests.server.helpers import TOKEN


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    # No ORCA unless a test asks for the fake_orca fixture. xTB is whatever this environment has:
    # tblite is a project dependency, so it is normally found (the fake agent never calls it).
    monkeypatch.delenv("ORCA_BIN", raising=False)
    monkeypatch.delenv("OPI_ORCA", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Settings(repo=REPO, runs_root=tmp_path / "runs", web_dir=REPO / "app" / "web", api_token=TOKEN,
                    token_was_generated=False, max_runs=1, cors_origins=["*"],
                    repo_url="https://example.invalid/molcurator",
                    agent_cmd=[sys.executable, str(HERE / "fake_agent.py")])


@pytest.fixture
def fake_orca(tmp_path, monkeypatch) -> Path:
    """An executable named orca, set as ORCA_BIN: preflight only checks that ORCA exists."""
    orca = tmp_path / "orca-bin" / "orca"
    orca.parent.mkdir()
    orca.write_text("#!/bin/sh\nexit 0\n")
    orca.chmod(orca.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ORCA_BIN", str(orca))
    return orca


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c
