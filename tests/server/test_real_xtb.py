"""One small real run through the API: the real `molcurator run` command and real xTB.

Skipped unless MOLCURATOR_TEST_XTB points to an xtb executable, e.g.
    MOLCURATOR_TEST_XTB=$(which xtb) pytest app/server/tests/test_real_xtb.py
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN, small_config, wait_for
from molcurator_api.main import create_app
from molcurator_api.settings import default_agent_cmd

XTB = os.environ.get("MOLCURATOR_TEST_XTB")
pytestmark = pytest.mark.skipif(not XTB or not Path(XTB).is_file(), reason="set MOLCURATOR_TEST_XTB to run")


def test_real_run_with_xtb(settings, monkeypatch):
    monkeypatch.setenv("XTB_BIN", XTB)
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
