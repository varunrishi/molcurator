"""run_agent and resume_agent: whole runs in their own folders (Phase 2, R7, R8.1, R8.3, R8.4)."""
import dataclasses
import json
from pathlib import Path

import pytest

from molcurator.agent.runner import resume_agent, run_agent
from molcurator.agent.toolset import Toolset
from molcurator.config import load_config
from tests.agent.fakes import FakeTools
from tests.agent.test_graph import raw_config


def test_run_agent_writes_a_complete_run_folder(tmp_path):
    """R8.1, R8.4: config copy, dataset, trace and summary in <runs_root>/<run_id>/; R8.3: every event reported."""
    events = []
    state = run_agent(raw_config(), tools=Toolset.from_object(FakeTools()), runs_root=tmp_path,
                      run_id="t", on_event=events.append)
    run_dir = tmp_path / "t"
    assert state["run_dir"] == str(run_dir) and state["error"] is None
    assert {"config.yaml", "dataset.jsonl", "summary.md", "traces"} <= {p.name for p in run_dir.iterdir()}
    assert load_config(run_dir / "config.yaml") == raw_config()
    assert len(events) == len((run_dir / "traces" / "trace.jsonl").read_text().splitlines())


def test_interrupted_run_resumes_to_the_same_result_with_one_line_per_node(tmp_path):
    """R7.1, R7.2: Ctrl-C during CURATE, then resume: same result as an uninterrupted run, no duplicate lines."""
    config, tools = raw_config(), Toolset.from_object(FakeTools())
    full = run_agent(config, tools=tools, runs_root=tmp_path, run_id="full")
    def ctrl_c(*args): raise KeyboardInterrupt  # not caught by guarded, like a real Ctrl-C
    with pytest.raises(KeyboardInterrupt):
        run_agent(config, tools=dataclasses.replace(tools, curate=ctrl_c), runs_root=tmp_path, run_id="cut")
    resumed = resume_agent("cut", runs_root=tmp_path, tools=tools)
    assert all(resumed[k] == full[k] for k in ("dataset_size", "round_stats", "stop_reason"))
    names = lambda state: {i: {**m, "xyz_path": m["xyz_path"] and Path(m["xyz_path"]).name}  # noqa: E731
                           for i, m in state["molecules"].items()}  # the run folder differs, nothing else
    assert names(resumed) == names(full)
    ids = lambda run: [json.loads(line)["event_id"] for line in (tmp_path / run / "traces" / "trace.jsonl").read_text().splitlines()]  # noqa: E731
    assert len(set(ids("cut"))) == len(ids("cut")) == len(ids("full")) + 1 and "cut:run_start:resume-1" in ids("cut")
    with pytest.raises(ValueError, match="nothing to resume"):
        resume_agent("cut", runs_root=tmp_path, tools=tools)
