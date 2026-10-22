"""API tests with the fake agent (real graph, trace and CURATE; fake chemistry). No xTB needed."""
import io
import json
import time
import zipfile

from molcurator.chem.properties import SCALAR_PROPERTIES

from tests.server.helpers import TOKEN, small_config, wait_for


# ------------------------------------------------------------------ system
def test_health_needs_no_token_and_reports_auth(client):
    r = client.get("/api/health", headers={"Authorization": ""})
    assert r.status_code == 200
    assert r.json()["auth_required"] is True


def test_endpoints_need_the_token(client):
    assert client.get("/api/system", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/system", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/system").status_code == 200


def test_system_reports_tools_and_capabilities(client):
    body = client.get("/api/system").json()
    assert body["tools"]["xtb"]["found"] is True
    assert body["tools"]["orca"]["found"] is False
    assert "value" not in json.dumps(body["tools"]["anthropic_key"])  # the key itself is never returned
    targets = {t["name"]: t for t in body["capabilities"]["targets"]}
    assert set(targets) == set(SCALAR_PROPERTIES)                   # read from the agent's own list
    assert targets["homo_lumo_gap"]["units"] == "eV" and targets["homo_lumo_gap"]["predict_method"] == "GFN2-xTB"
    assert targets["s1_t1_gap"]["needs_orca"] is True and targets["s1_t1_gap"]["predict_method"] == "B97-3c"


def test_system_finds_orca_from_orca_bin(client, fake_orca):
    orca = client.get("/api/system").json()["tools"]["orca"]
    assert orca["found"] is True and orca["source"] == "ORCA_BIN" and orca["path"] == str(fake_orca.resolve())


def test_presets_describe_their_predict_level(client):
    presets = {p["name"]: p for p in client.get("/api/presets").json()}
    assert presets["homo_lumo"]["predict_level"]["label"] == "GFN2-xTB corrected to DFT-like"
    assert presets["tadf"]["predict_level"]["method"] == "B97-3c"
    assert any("ORCA" in n for n in presets["tadf"]["notes"])       # no ORCA in this test
    assert len(presets["homo_lumo"]["config"]["seeds"]) == 10  # read from data/seeds/homo_lumo.csv (seeds_file)
    assert not presets["homo_lumo"]["notes"] and presets["tadf"]["notes"]  # only tadf's seed is a PLACEHOLDER


def test_validate_reports_problems_and_warnings(client):
    bad = client.post("/api/config/validate", json={"config": {"target": {"name": "homo_lumo_gap"}, "seeds": ["C"]}}).json()
    assert bad["valid"] is False and any("target" in p for p in bad["problems"])

    tadf = client.post("/api/config/validate", json={"config": small_config(target={"name": "s1_t1_gap", "max": 0.2})}).json()
    assert tadf["valid"] is False and any("needs ORCA" in p for p in tadf["problems"])

    unknown = client.post("/api/config/validate", json={"config": small_config(target={"name": "solubility", "max": 1})}).json()
    assert unknown["valid"] is False and any("not a single-number property" in p for p in unknown["problems"])

    ok = client.post("/api/config/validate", json={"config": small_config()}).json()
    assert ok["valid"] is True and ok["problems"] == []
    assert any("QM validation is switched off" in w for w in ok["warnings"])
    assert any("raw GFN2-xTB" in w for w in ok["warnings"])  # no predict.correction: the offset note
    correction = {"slope": 0.6915, "intercept": 3.2347, "residual_sd": 0.455, "xtb_range": [1.02, 8.84],
                  "fitted_on": "60 pairs"}
    corrected = client.post("/api/config/validate",
                            json={"config": small_config(predict={"n_xtb": 4, "correction": correction})}).json()
    assert corrected["valid"] is True and not any("raw GFN2-xTB" in w for w in corrected["warnings"])


def test_inspect_flags_what_the_tools_reject(client):
    benzene = client.post("/api/chem/inspect", json={"smiles": "C1=CC=CC=C1"}).json()
    assert benzene["valid"] and benzene["canonical"] == "c1ccccc1" and benzene["problems"] == []
    assert benzene["xyz"].splitlines()[0].strip() == "12"
    assert client.post("/api/chem/inspect", json={"smiles": "[NH4+]", "xyz": False}).json()["problems"]
    assert client.post("/api/chem/inspect", json={"smiles": "not a smiles"}).json()["valid"] is False


def test_start_refuses_what_cannot_run(client):
    r = client.post("/api/runs", json={"config": small_config(qm={"backend": "orca"})})  # no ORCA on this server
    assert r.status_code == 422 and any("ORCA" in p for p in r.json()["detail"]["problems"])
    r = client.post("/api/runs", json={"config": small_config(decisions="llm")})  # no API key
    assert r.status_code == 422


def test_bad_ids_are_rejected(client):
    assert client.get("/api/runs/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/api/runs/no-such-run").status_code == 404


# ------------------------------------------------------------------ a whole run
def test_run_to_completion_and_read_results(client):
    r = client.post("/api/runs", json={"config": small_config(), "run_id": "t-complete"})
    assert r.status_code == 202, r.text
    assert r.json()["run_id"] == "t-complete"

    done = wait_for(client, "t-complete", {"finished", "failed"})
    assert done["status"] == "finished" and done["stop_reason"] == "max_rounds"
    assert done["budget"]["rounds_done"] == 2 and len(done["rounds"]) == 2
    assert done["files"]["dataset.csv"] and done["files"]["summary.md"]

    listed = client.get("/api/runs").json()
    assert [i["run_id"] for i in listed] == ["t-complete"]

    first = client.get("/api/runs/t-complete", params={"events_since": 0}).json()
    nodes = [e["node"] for e in first["events"]]
    assert nodes[0] == "run_start" and nodes[-1] == "write_summary"
    assert first["events_next"] == len(first["events"])
    assert "results" not in first["events"][2]["outputs"]  # compact: counts instead of lists
    later = client.get("/api/runs/t-complete", params={"events_since": first["events_next"]}).json()
    assert later["events"] == []

    raw = client.get("/api/runs/t-complete/events", params={"since": 0, "limit": 3}).json()
    assert len(raw["events"]) == 3 and raw["next"] == 3

    molecules = client.get("/api/runs/t-complete/molecules").json()
    dataset = client.get("/api/runs/t-complete/dataset").json()
    curated = [m for m in molecules if m["curated"]]
    assert len(curated) == len(dataset) > 0
    assert all(m["in_window"] for m in curated)  # CURATE keeps molecules whose best estimate is in the window
    assert {m["best_level"] for m in curated} <= {"xtb", "ml"}  # QM is off

    with_xyz = next(m for m in molecules if m["has_xyz"])
    assert client.get(f"/api/runs/t-complete/molecules/{with_xyz['id']}/xyz").status_code == 200

    csv_text = client.get("/api/runs/t-complete/files/dataset.csv").text
    assert csv_text.startswith("id,smiles")
    assert client.get("/api/runs/t-complete/files/secret.txt").status_code == 404

    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/runs/t-complete/archive").content))
    assert "t-complete/traces/trace.jsonl" in archive.namelist()

    evaluation = client.get("/api/runs/t-complete/evaluation").json()
    assert "overall" in evaluation
    assert "=== " in client.get("/api/runs/t-complete/log").text  # the API writes a header line per launch


def test_stop_then_resume_finishes_without_duplicate_steps(client, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_STEP_SECONDS", "0.3")
    client.post("/api/runs", json={"config": small_config(budget={"max_rounds": 3, "target_dataset_size": 1000}),
                                   "run_id": "t-stop"})
    deadline = time.time() + 30
    while client.get("/api/runs/t-stop").json().get("event_count", 0) < 4 and time.time() < deadline:
        time.sleep(0.2)
    assert client.post("/api/runs/t-stop/resume").status_code == 409  # still running

    assert client.post("/api/runs/t-stop/stop").status_code == 202
    stopped = wait_for(client, "t-stop", {"interrupted", "finished"})
    assert stopped["status"] == "interrupted" and stopped["resumable"]

    monkeypatch.setenv("FAKE_AGENT_STEP_SECONDS", "0")
    assert client.post("/api/runs/t-stop/resume").status_code == 202
    done = wait_for(client, "t-stop", {"finished", "failed"})
    assert done["status"] == "finished"

    events = client.get("/api/runs/t-stop/events").json()["events"]
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids))
    assert any(e.get("resumed") for e in events if e["node"] == "run_start")


def test_run_limit_is_enforced(client, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_STEP_SECONDS", "0.3")
    assert client.post("/api/runs", json={"config": small_config(), "run_id": "t-first"}).status_code == 202
    second = client.post("/api/runs", json={"config": small_config(), "run_id": "t-second"})
    assert second.status_code == 409 and "limit" in second.json()["detail"]
    assert client.post("/api/runs", json={"config": small_config(), "run_id": "t-first"}).status_code == 409
    client.post("/api/runs/t-first/stop")
    wait_for(client, "t-first", {"interrupted", "finished"})


def test_web_app_is_served_at_root(client):
    r = client.get("/", headers={"Authorization": ""})
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_stop_kills_a_run_that_ignores_ctrl_c_and_its_helpers(client, settings, monkeypatch):
    import os
    import subprocess
    from server import run_manager
    monkeypatch.setattr(run_manager, "STOP_GRACE_SECONDS", 1)
    monkeypatch.setenv("FAKE_AGENT_STUBBORN", "1")
    assert client.post("/api/runs", json={"config": small_config(), "run_id": "t-stubborn"}).status_code == 202
    helper_file = settings.runs_root / "helper.pid"
    deadline = time.time() + 20
    while not helper_file.exists() and time.time() < deadline:
        time.sleep(0.1)
    helper = int(helper_file.read_text())
    client.post("/api/runs/t-stubborn/stop")
    stopped = wait_for(client, "t-stubborn", {"interrupted", "failed"}, timeout=20)
    assert stopped["status"] == "interrupted"
    time.sleep(0.5)
    try:
        os.kill(helper, 0)
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(helper)], capture_output=True, text=True).stdout
        alive = bool(state.strip()) and not state.strip().startswith("Z")  # a zombie is already dead (Linux, macOS)
    except ProcessLookupError:
        alive = False
    assert not alive


def test_raw_xtb_values_are_shown_for_corrected_runs(client):
    correction = {"slope": 0.5, "intercept": 3.0, "residual_sd": 0.4, "xtb_range": [1.0, 2.0], "fitted_on": "test"}
    config = small_config(predict={"n_xtb": 4, "correction": correction}, budget={"max_rounds": 1, "target_dataset_size": 1000})
    assert client.post("/api/runs", json={"config": config, "run_id": "corrected"}).status_code == 202
    assert wait_for(client, "corrected", {"finished"})["predict_level"]["corrected"] is True
    predicted = [m for m in client.get("/api/runs/corrected/molecules").json() if m["xtb"] is not None]
    assert predicted
    for m in predicted:
        assert abs(0.5 * m["xtb_raw"] + 3.0 - m["xtb"]) < 1e-9
        assert m["xtb_extrapolated"] == (not 1.0 <= m["xtb_raw"] <= 2.0)
