"""The prompt-to-run assistant, with a fake Claude: the real merge, validation and checks."""
from types import SimpleNamespace

from server.assistant import RunDraft


class FakeClaude:
    """Returns the queued drafts in order, as messages.parse would; records what was sent."""

    def __init__(self, *drafts):
        self.drafts, self.sent = list(drafts), []
        self.messages = self

    def parse(self, **kwargs):
        self.sent.append(kwargs)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return SimpleNamespace(parsed_output=draft, content=[])


def use_fake(client, monkeypatch, *drafts) -> FakeClaude:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = FakeClaude(*drafts)
    client.app.state.assistant_client = lambda settings: fake
    return fake


def test_assistant_is_hidden_without_a_key(client):
    assert client.get("/api/system").json()["assistant"]["available"] is False
    assert client.post("/api/assistant/plan", json={"prompt": "hi"}).status_code == 503


def test_a_complete_prompt_gives_a_ready_plan(client, monkeypatch):
    use_fake(client, monkeypatch, RunDraft(
        understood=True, target_property="homo_lumo_gap", window_min=2.8, window_max=3.2,
        seed_smiles="c1ccc(-c2cccs2)s1", seed_name="2,2'-bithiophene", max_rounds=3, reply="Set up."))
    assert client.get("/api/system").json()["assistant"]["available"] is True
    plan = client.post("/api/assistant/plan", json={"prompt": "bithiophene, gap 2.8-3.2 eV, 3 rounds"}).json()
    assert plan["ready"] is True, plan["problems"]
    assert plan["config"]["target"] == {"name": "homo_lumo_gap", "min": 2.8, "max": 3.2, "units": "eV"}
    assert plan["config"]["seeds"] == ["c1csc(-c2cccs2)c1"]          # canonicalised by RunConfig
    assert plan["config"]["budget"]["max_rounds"] == 3
    assert plan["seed"]["formula"] == "C8H6S2"
    assert any("from the name" in w for w in plan["warnings"])      # a name-derived SMILES is flagged
    assert plan["config"]["qm"]["enabled"] is False                # no ORCA in this test
    assert "rounds" not in plan["defaults_used"] and "candidates per round" in plan["defaults_used"]


def test_missing_window_and_seed_are_never_filled_from_the_preset(client, monkeypatch):
    use_fake(client, monkeypatch, RunDraft(understood=True, reply="Which molecule?", missing=["seed molecule"]))
    plan = client.post("/api/assistant/plan", json={"prompt": "find me some molecules"}).json()
    assert plan["ready"] is False
    assert any("target window" in p for p in plan["problems"])
    assert any("seed" in p for p in plan["problems"])


def test_a_follow_up_changes_only_what_it_mentions(client, monkeypatch):
    fake = use_fake(client, monkeypatch,
                    RunDraft(understood=True, window_min=3.0, window_max=3.5, seed_smiles="c1ccccc1", reply="ok"),
                    RunDraft(understood=True, max_rounds=8, reply="Eight rounds."))
    first = client.post("/api/assistant/plan", json={"prompt": "benzene 3-3.5 eV"}).json()
    second = client.post("/api/assistant/plan", json={"prompt": "use 8 rounds", "current": first["config"]}).json()
    assert second["ready"] is True
    assert second["config"]["budget"]["max_rounds"] == 8
    assert second["config"]["target"]["min"] == 3.0 and second["config"]["seeds"] == ["c1ccccc1"]
    assert "Current configuration" in fake.sent[1]["messages"][0]["content"]


def test_qm_is_on_by_default_when_orca_is_there(client, monkeypatch, fake_orca):
    use_fake(client, monkeypatch, RunDraft(understood=True, window_min=4.0, window_max=4.5,
                                           seed_smiles="c1ccccc1", reply="ok"))
    plan = client.post("/api/assistant/plan", json={"prompt": "benzene 4-4.5 eV"}).json()
    assert plan["ready"] is True, plan["problems"]
    assert plan["config"]["qm"]["enabled"] is True
    assert plan["config"]["predict"]["correction"] is not None      # from configs/homo_lumo.yaml


def test_qm_is_off_with_a_note_without_orca(client, monkeypatch):
    use_fake(client, monkeypatch, RunDraft(understood=True, window_min=4.0, window_max=4.5,
                                           seed_smiles="c1ccccc1", reply="ok"))
    plan = client.post("/api/assistant/plan", json={"prompt": "benzene 4-4.5 eV"}).json()
    assert plan["config"]["qm"]["enabled"] is False
    assert any("ORCA was not found" in w for w in plan["warnings"])


def test_a_tadf_run_starts_from_the_tadf_preset_and_needs_orca(client, monkeypatch):
    use_fake(client, monkeypatch, RunDraft(
        understood=True, target_property="s1_t1_gap", window_max=0.2,
        seed_smiles="c1ccccc1", qm=True, reply="TADF run."))
    plan = client.post("/api/assistant/plan", json={"prompt": "TADF emitters with QM"}).json()
    assert plan["ready"] is False
    assert plan["config"]["target"]["name"] == "s1_t1_gap"
    assert plan["config"]["predict"]["n_xtb"] == 20                  # from configs/tadf.yaml
    assert any("PREDICT runs B97-3c" in p for p in plan["problems"])  # TD-DFT PREDICT, ORCA not installed


def test_a_property_the_tools_do_not_compute_is_refused(client, monkeypatch):
    use_fake(client, monkeypatch, RunDraft(understood=True, target_property="other", reply="?"))
    plan = client.post("/api/assistant/plan", json={"prompt": "find good solubility"}).json()
    assert plan["ready"] is False and any("not one the tools compute" in p for p in plan["problems"])


def test_claude_errors_are_reported(client, monkeypatch):
    use_fake(client, monkeypatch, RuntimeError("overloaded"))
    r = client.post("/api/assistant/plan", json={"prompt": "benzene 3-3.5 eV"})
    assert r.status_code == 502 and "overloaded" in r.json()["detail"]


def test_a_follow_up_without_a_seed_still_needs_one(client, monkeypatch):
    use_fake(client, monkeypatch,
             RunDraft(understood=True, window_min=3.0, window_max=3.5, reply="Which seed?"),
             RunDraft(understood=True, max_rounds=4, reply="Four rounds."))
    first = client.post("/api/assistant/plan", json={"prompt": "gap 3-3.5 eV"}).json()
    assert first["config"]["seeds"] == []                           # the preset's placeholder seed is not used
    second = client.post("/api/assistant/plan", json={"prompt": "4 rounds", "current": first["config"]}).json()
    assert second["ready"] is False and any("seed" in p for p in second["problems"])

