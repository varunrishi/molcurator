"""Agreed docs/trace-format.md rows, including unsupported and unavailable evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace

NODES = ["plan_round", "generate", "predict", "train", "ml_predict", "screen", "curate",
         "close_round", "continue_or_stop", "write_summary"]


def v1_trace():
    config = dict(qm=dict(enabled=False), predict=dict(n_xtb=1), train=dict(min_examples=2),
        target=dict(name="homo_lumo_gap", min=3., max=3.5, units="eV"), seeds=["CC"],
        screening=dict(margin=.2), decisions="rules", generation=dict(generators=["stoned_selfies"],
        max_candidates=10, max_mutation_strength=3),
        budget=dict(max_rounds=1, max_qm_calls=10, max_wall_time=1000, target_dataset_size=10))
    plan = dict(parents=["seed-0"], generator="stoned_selfies", n_candidates=2,
                mutation_strength=1, reason="seed neighborhood")
    stats = dict(generated=2, duplicates=0, xtb_runs=1, ml_predicted=0, unscored=1,
                 failed=0, screened_in=1, selected=0, qm_calls=0, hits=1)
    def event(node, inputs=None, outputs=None, **extra):
        return dict(trace_version=1, run_id="demo", event_id="demo:run_start" if node == "run_start" else f"demo:r1:{node}",
                    node=node, round=None if node == "run_start" else 1, status="ok", reason=None, error=None,
                    inputs=inputs or {}, outputs=outputs or {}, **extra)
    events = [event("run_start", dict(config=config, nodes=NODES.copy()), resumed=False),
        event("plan_round", outputs=dict(round_plan=plan, qm_batch=[])),
        event("generate", dict(round_plan=copy.deepcopy(plan)), dict(results=[["a", "generated", "CCO"], ["b", "generated", "CCN"]])),
        event("predict", dict(candidate_ids=["a"]), dict(results=[["a", "predicted", 3.2]])),
        event("train"), event("ml_predict", dict(candidate_ids=["b"]), dict(results=[["b", "unscored", None]])),
        event("screen", dict(candidate_ids=["a"]), dict(results=[["a", "screened_in", None]])),
        event("curate", dict(candidate_ids=["a"]), dict(dataset_size=1, results=[["a", "curated", None]])),
        event("close_round", outputs=dict(round_stats=stats)),
        event("continue_or_stop", outputs=dict(stop_reason="max_rounds")),
        event("write_summary", outputs=dict(stop_reason="max_rounds"))]
    events[4].update(status="skipped", reason="below_min_examples")
    start = datetime(2026, 10, 22, tzinfo=timezone.utc)
    for i, e in enumerate(events):
        e["started_at"] = (start + timedelta(seconds=i)).isoformat(timespec="milliseconds")
        e["ended_at"] = e["started_at"]
    return events


def codes(report):
    return {f["code"] for f in report["findings"]}


def test_documented_v1_infers_config_and_reports_qm_not_measurable():
    events = v1_trace(); original = copy.deepcopy(events)
    report = evaluate_trajectory(events)
    assert report["overall"] == "pass", report["findings"]
    assert report["metadata"]["trace_contract"] == "agent-v1"
    assert report["metadata"]["overall_scope"] == "available_evidence_only"
    assert report["capabilities"]["qm_behavior"]["label"] == "QM behavior: not measurable"
    assert report["capabilities"]["qm_behavior"]["status"] == "not_measurable"
    assert report["capabilities"]["tool_return_order"]["status"] == "not_measurable"
    assert report["summary"]["observed_qm_launches"] is None
    assert report["summary"]["reported_qm_calls"] == 0
    assert report["summary"]["dataset_size"] == 1
    assert events == original


def test_rules_metadata_does_not_claim_llm_execution():
    events = v1_trace()
    metadata = dict(decision={}, source="rule", fallback="rules_mode", retried=False,
                    prompt=None, raw_response=None, duration_s=0.)
    events[1]["llm"] = metadata
    report = evaluate_trajectory(events)
    assert report["overall"] == "pass"
    assert report["summary"]["recorded_rule_decisions"] == 1
    assert report["capabilities"]["llm_behavior"]["status"] == "not_measurable"
    metadata["fallback"] = "api_error"
    assert "invalid_rule_metadata" in codes(evaluate_trajectory(events))


def test_declared_node_order_is_used_instead_of_legacy_order():
    events = v1_trace()
    # This graph declares its below-threshold training check before prediction.
    events[0]["inputs"]["nodes"][2:4] = ["train", "predict"]
    events[3], events[4] = events[4], events[3]
    for i, e in enumerate(events):
        e["started_at"] = e["ended_at"] = f"2026-10-22T00:00:{i:02d}+00:00"
    assert evaluate_trajectory(events)["checks"]["ordering"] == "pass"
    events[0]["inputs"]["nodes"] = NODES.copy()
    assert "node_out_of_order" in codes(evaluate_trajectory(events))


@pytest.mark.parametrize("change", [lambda e: e[3]["outputs"]["results"].append(["x", "predicted", 3.2]),
    lambda e: e[3]["outputs"]["results"][0].__setitem__(1, "ok"),
    lambda e: e[3]["outputs"]["results"][0].__setitem__(2, float("inf")),
    lambda e: e[2]["outputs"]["results"].reverse(),
    lambda e: e[6]["outputs"]["results"][0].__setitem__(1, "screened_out"),
    lambda e: e[8]["outputs"]["round_stats"].__setitem__("hits", 9)])
def test_bad_compact_results_and_stats_are_detected(change):
    events = v1_trace(); change(events)
    assert evaluate_trajectory(events)["checks"]["tool_correctness"] == "fail"


def test_training_model_without_training_inputs_is_supported():
    events = v1_trace()
    events[0]["inputs"]["config"]["train"]["min_examples"] = 1
    events[4].update(status="ok", reason=None, outputs=dict(model=dict(model_path="model.json", n_examples=1, metrics={"mae": .1})))
    events[5]["outputs"]["results"] = [["b", "ml_predicted", 5.0]]
    events[6]["inputs"]["candidate_ids"] = ["a", "b"]
    events[6]["outputs"]["results"].append(["b", "screened_out", None])
    events[8]["outputs"]["round_stats"].update(ml_predicted=1, unscored=0)
    assert evaluate_trajectory(events)["overall"] == "pass"
    events[4]["outputs"]["model"]["n_examples"] = 2
    assert evaluate_trajectory(events)["checks"]["tool_correctness"] == "fail"


def test_no_op_nodes_can_omit_results_and_candidate_ids():
    events = v1_trace()
    events[0]["inputs"]["config"]["predict"]["n_xtb"] = 2
    events[3]["inputs"]["candidate_ids"].append("b")
    events[3]["outputs"]["results"].append(["b", "failed", "embedding failed"])
    events[5].update(status="skipped", reason="no_candidates_left", inputs={}, outputs={})
    events[7].update(inputs={}, outputs={})  # use an outside-target a, so there are no hits
    events[3]["outputs"]["results"][0][2] = 3.6
    events[8]["outputs"]["round_stats"].update(xtb_runs=2, unscored=0, failed=1, hits=0)
    assert evaluate_trajectory(events)["overall"] == "pass"


def test_full_step_failure_routes_to_summary_and_records_error():
    events = v1_trace()
    failed = dict(events[3], status="failed", error="predict: RuntimeError: test", inputs={}, outputs={})
    summary = dict(events[-1], outputs=dict(stop_reason="error"))
    report = evaluate_trajectory(events[:3] + [failed, summary])
    assert report["overall"] == "pass", report["findings"]
    assert "continued_after_tool_failure" in codes(evaluate_trajectory(events[:3] + [failed] + events[4:]))


def test_unavailable_and_future_evidence_is_explicit():
    events = v1_trace(); events[0]["resumed"] = True
    report = evaluate_trajectory(events)
    assert report["overall"] == "not_assessable"
    assert "unsupported_resume" in codes(report)
    events = v1_trace(); events[0]["inputs"]["config"]["qm"]["enabled"] = True
    report = evaluate_trajectory(events)
    assert report["overall"] == "not_assessable"
    assert report["summary"]["observed_qm_launches"] is None
    assert "unsupported_qm_behavior" in codes(report)
    assert evaluate_trajectory(v1_trace()[1:])["overall"] == "not_assessable"


def test_mode_override_cannot_hide_recorded_configuration():
    with pytest.raises(ValueError, match="conflicts"):
        evaluate_trajectory(v1_trace(), qm_enabled=True)


def test_placeholder_smiles_cannot_establish_molecular_identity():
    events = v1_trace(); events[2]["outputs"]["results"][0][2] = "fake-r1-000"
    report = evaluate_trajectory(events)
    assert report["overall"] == "not_assessable"
    assert "unavailable_molecular_identity" in codes(report)


def test_budget_override_is_recorded_and_checked():
    report = evaluate_trajectory(v1_trace(), budgets={"max_wall_time": 1})
    assert "wall_time_exceeded" in codes(report)
    assert report["metadata"]["budget_overrides"] == dict(max_wall_time=1)


def test_cli_reads_v1_without_explicit_budget_flags(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in v1_trace()))
    output = tmp_path / "report.json"
    script = Path(__file__).resolve().parents[1] / "scripts/evaluate_trajectory.py"
    completed = subprocess.run([sys.executable, "-B", str(script), str(path), "--out", str(output)],
                               cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "QM behavior: not measurable" in completed.stdout
    report = json.loads(output.read_text())
    assert report["metadata"]["source"]["sha256"]
    events, source = load_trace(path)
    assert evaluate_trajectory(events, source=source)["metadata"]["trace_contract"] == "agent-v1"


@pytest.mark.parametrize("index", [3, 5, 6, 7])
def test_omitted_effects_do_not_invent_failures(index):
    events = v1_trace(); events[index].update(inputs={}, outputs={})
    report = evaluate_trajectory(events)
    assert report["overall"] == "not_assessable", report["findings"]
    assert "unavailable_node_effects" in codes(report)
    if index == 7:
        assert report["summary"]["dataset_size"] is None


def test_continue_cannot_ignore_reached_budget():
    events = v1_trace(); events[-2]["outputs"] = dict(round=2)
    assert "continued_after_budget_limit" in codes(evaluate_trajectory(events))


def test_unknown_node_and_unknown_skip_reason_are_unassessable():
    events = v1_trace(); events[4]["reason"] = "future_reason"
    assert "unsupported_skip_reason" in codes(evaluate_trajectory(events))
    events = v1_trace(); events[4].update(node="future_training", status="ok", reason=None, event_id="demo:r1:future_training")
    events[0]["inputs"]["nodes"][3] = "future_training"
    assert "unsupported_node" in codes(evaluate_trajectory(events))


def test_qm_nodes_are_not_silently_accepted_with_qm_disabled():
    events = v1_trace(); events[4].update(node="validate", status="ok", reason=None, event_id="demo:r1:validate")
    events[0]["inputs"]["nodes"][3] = "validate"
    assert "qm_called_while_disabled" in codes(evaluate_trajectory(events))


def test_compact_per_molecule_failure_can_be_skipped():
    events = v1_trace()
    events[3]["outputs"]["results"] = [["a", "failed", "embedding failed"]]
    events[6].update(inputs={}, outputs={})
    events[7].update(inputs={}, outputs={})
    events[8]["outputs"]["round_stats"].update(failed=1, screened_in=0, hits=0)
    assert evaluate_trajectory(events)["overall"] == "pass"


def test_compact_two_round_flow_and_cumulative_dataset_size():
    events = v1_trace()[:-1]
    events[0]["inputs"]["config"]["budget"]["max_rounds"] = 2
    events[0]["inputs"]["config"]["train"]["min_examples"] = 5
    events[-1]["outputs"] = dict(round=2)
    second = copy.deepcopy(v1_trace()[1:])
    def rename(value):
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v) for v in value]
        return {"a": "c", "b": "d", "CCO": "CCCO", "CCN": "CCCN"}.get(value, value) if isinstance(value, str) else value
    second = rename(second)
    for e in second:
        e["round"] = 2
        e["event_id"] = e["event_id"].replace(":r1:", ":r2:")
        if e["node"] == "curate":
            e["outputs"]["dataset_size"] = 2
    events += second
    start = datetime(2026, 10, 22, tzinfo=timezone.utc)
    for i, e in enumerate(events):
        e["started_at"] = e["ended_at"] = (start + timedelta(seconds=i)).isoformat()
    report = evaluate_trajectory(events)
    assert report["overall"] == "pass", report["findings"]
    assert report["summary"]["rounds"] == 2
    assert report["summary"]["dataset_size"] == 2
