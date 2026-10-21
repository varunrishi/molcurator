"""Run traces written by the v1 graph (Phase 2, R6.1, R6.2; format agreed in issue #13)."""
import json

from molcurator.agent.graph import NODES
from tests.agent.fakes import FakeTools
from tests.agent.test_graph import run_graph

KEYS = {"trace_version", "run_id", "event_id", "node", "round", "started_at", "ended_at",
        "status", "reason", "error", "inputs", "outputs"}  # on every line
DECISION_NODES = {"plan_round", "continue_or_stop", "write_summary"}  # select_qm_batch too, once QM is wired


def read_trace(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "traces" / "trace.jsonl").read_text().splitlines()]


def test_every_node_writes_one_line_in_graph_order(tmp_path):
    """R6.1: run_start first, then one line per node in graph order each round, unique event ids."""
    run_graph(tmp_path, target_dataset_size=1000, max_rounds=2)
    lines = read_trace(tmp_path)
    assert lines[0]["node"] == "run_start" and lines[0]["inputs"]["nodes"] == NODES
    assert [e["node"] for e in lines[1:]] == NODES[:-1] * 2 + ["write_summary"]  # summary once, at the end
    assert len({e["event_id"] for e in lines}) == len(lines)
    assert all(KEYS <= set(e) for e in lines)


def test_tool_lines_hold_per_molecule_results_and_decisions_say_how(tmp_path):
    """R6.1, R6.2, #13: per-molecule evidence on tool lines; an llm block only where a decision was made."""
    state = run_graph(tmp_path, tools=FakeTools(predict_fail_rate=0.1))
    lines = {e["node"]: e for e in read_trace(tmp_path) if e["round"] == 1}  # one round: each node once
    stats = state["round_stats"][0]
    assert len(lines["generate"]["outputs"]["results"]) == stats["generated"]
    predicted = lines["predict"]["outputs"]["results"]
    assert len(predicted) == stats["xtb_runs"] and any(r[1] == "failed" for r in predicted)
    assert all(isinstance(r[2], str) if r[1] == "failed" else isinstance(r[2], float) for r in predicted)
    assert (lines["train"]["status"], lines["train"]["reason"]) == ("skipped", "below_min_examples")
    assert {n for n, e in lines.items() if "llm" in e} <= DECISION_NODES
    assert lines["plan_round"]["llm"]["source"] == "rule" and lines["plan_round"]["llm"]["fallback"] == "rules_mode"


def test_crashed_step_gets_a_failed_line_then_the_summary(tmp_path):
    """R1.7, R6.1, #13: the failing step's line is "failed" and names it; the next line is WRITE SUMMARY."""
    run_graph(tmp_path, tools=FakeTools(crash_step="predict"))
    lines = read_trace(tmp_path)
    assert [e["node"] for e in lines] == ["run_start", "plan_round", "generate", "predict", "write_summary"]
    assert lines[3]["status"] == "failed" and lines[3]["error"].startswith("predict: ")
    assert lines[4]["outputs"]["stop_reason"] == "error"
