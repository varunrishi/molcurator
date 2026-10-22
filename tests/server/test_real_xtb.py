"""One small real run through the API: the real `molcurator run` command and real xTB (through tblite).

Skipped where tblite is not installed (e.g. Windows, where xTB needs ORCA).
"""
import importlib.util

import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import default_agent_cmd
from tests.server.conftest import TOKEN, small_config, wait_for

pytestmark = pytest.mark.skipif(importlib.util.find_spec("tblite") is None, reason="tblite not installed")


def test_real_run_with_xtb(settings):
    settings.agent_cmd = default_agent_cmd()
    config = small_config(seeds=["c1ccc(-c2cccs2)s1"], predict={"n_xtb": 6},
                          train={"min_examples": 1000}, budget={"max_rounds": 1, "target_dataset_size": 1000})
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        r = client.post("/api/runs", json={"config": config, "run_id": "real-xtb"})
        assert r.status_code == 202, r.text
        done = wait_for(client, "real-xtb", {"finished", "failed"}, timeout=600)
        assert done["status"] == "finished", client.get("/api/runs/real-xtb/log").text

        molecules = client.get("/api/runs/real-xtb/molecules").json()
        predicted = [m for m in molecules if m["xtb"] is not None]
        assert predicted, molecules
        assert all(m["has_xyz"] for m in predicted)
        xyz = client.get(f"/api/runs/real-xtb/molecules/{predicted[0]['id']}/xyz").text
        assert int(xyz.splitlines()[0]) > 0
