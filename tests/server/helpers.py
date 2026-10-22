"""Small helpers shared by the server tests (kept out of conftest.py so tests can import them)."""
import time

from fastapi.testclient import TestClient

TOKEN = "test-token"


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
