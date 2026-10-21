"""run_agent: one call runs a whole run into its own folder (Phase 2, R8.1, R8.3, R8.4)."""
from molcurator.agent.runner import run_agent
from molcurator.agent.toolset import Toolset
from molcurator.config import load_config
from tests.agent.fakes import FakeTools
from tests.agent.test_graph import CONFIG


def test_run_agent_writes_a_complete_run_folder(tmp_path):
    """R8.1, R8.4: config copy, dataset, trace and summary in <runs_root>/<run_id>/; R8.3: every event reported."""
    events = []
    state = run_agent(load_config(CONFIG), tools=Toolset.from_object(FakeTools()), runs_root=tmp_path,
                      run_id="t", on_event=events.append)
    run_dir = tmp_path / "t"
    assert state["run_dir"] == str(run_dir) and state["error"] is None
    assert {"config.yaml", "dataset.jsonl", "summary.md", "traces"} <= {p.name for p in run_dir.iterdir()}
    assert load_config(run_dir / "config.yaml") == load_config(CONFIG)
    assert len(events) == len((run_dir / "traces" / "trace.jsonl").read_text().splitlines())
