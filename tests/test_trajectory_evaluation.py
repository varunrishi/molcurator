"""Synthetic complete and faulty traces; no agent, LLM or chemistry execution."""
import copy
from datetime import datetime, timedelta, timezone
import json

import pytest

from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace

METHOD = "dft:B3LYP/def2-SVP"
BUDGETS = dict(max_rounds=3, max_qm_calls=10, max_wall_time=1000, target_dataset_size=10)


def candidate(cid, smiles):
    return dict(id=cid, smiles=smiles, parent_smiles="CC", round=1, generator="stoned_selfies")


def prediction(cid):
    return dict(candidate_id=cid, status="ok", value=3.2, error=None, xyz_path=f"{cid}.xyz")


def quantum(cid):
    return dict(candidate_id=cid, status="ok", value=3.25, error=None, method=METHOD,
                electronic_calls_attempted=1, cache_hit=False)


def entry(cid, smiles):
    return dict(id=cid, smiles=smiles, xyz_path=f"{cid}.xyz", properties={METHOD: 3.25},
                validated=True, provenance=dict(seeds="CC", parent="CC", round="1"))


def stamp(events):
    start = datetime(2026, 10, 21, tzinfo=timezone.utc)
    for i, event in enumerate(events):
        event["started_at"] = (start + timedelta(seconds=i * 2)).isoformat()
        event["ended_at"] = (start + timedelta(seconds=i * 2 + 1)).isoformat()
    return events


def event(node, inputs=None, outputs=None, **changes):
    return dict(dict(trace_version=1, run_id="synthetic", event_id=f"r1-{node}", node=node,
                     round=1, status="ok", inputs=inputs or {}, outputs=outputs or {}, error=None), **changes)


def trace():
    ids = ["a", "b"]
    return stamp([
        event("plan_round"),
        event("generate", dict(parents=["CC"], settings=dict(n_candidates=2)),
              dict(candidates=[candidate("a", "CCO"), candidate("b", "CCN")])),
        event("predict", dict(candidate_ids=ids, calculation_fingerprints={"a": "x-a", "b": "x-b"}),
              dict(results=[prediction(cid) for cid in ids])),
        event("screen", dict(candidate_ids=ids), dict(screened_ids=ids)),
        event("select_qm_batch", outputs=dict(candidate_ids=ids)),
        event("validate", dict(candidate_ids=ids, qm_method=METHOD,
                               calculation_fingerprints={"a": "q-a", "b": "q-b"}),
              dict(results=[quantum(cid) for cid in ids])),
        event("curate", dict(entries=[entry("a", "CCO"), entry("b", "CCN")]), dict(dataset_size=2)),
        event("close_round"),
        event("continue_or_stop", outputs={"continue": False}),
        event("write_summary", outputs=dict(stop_reason="llm_decision")),
    ])


def evaluate(events, **kwargs):
    return evaluate_trajectory(events, budgets=kwargs.pop("budgets", BUDGETS), **kwargs)


def codes(report):
    return {finding["code"] for finding in report["findings"]}


def test_complete_trace_passes_and_inputs_unchanged():
    events = trace()
    original = copy.deepcopy(events)
    report = evaluate(events)
    assert report["overall"] == "pass", report["findings"]
    assert report["summary"]["observed_qm_launches"] == 2
    assert report["summary"]["dataset_size"] == 2
    assert events == original
    assert evaluate(events) == report


@pytest.mark.parametrize("mode", ["missing", "extra", "reordered", "duplicate"])
def test_tool_result_identity_order_and_cardinality(mode):
    events = trace()
    results = events[2]["outputs"]["results"]
    if mode == "missing":
        results.pop()
    elif mode == "extra":
        results.append(prediction("unknown"))
    elif mode == "reordered":
        results.reverse()
    else:
        results[1] = prediction("a")
    assert "invalid_tool_call" in codes(evaluate(events))


@pytest.mark.parametrize("field,value", [("value", float("inf")), ("value", None),
    ("xyz_path", None), ("status", "unknown"), ("error", "contradiction")])
def test_bad_predictions_are_detected(field, value):
    events = trace()
    events[2]["outputs"]["results"][0][field] = value
    assert evaluate(events)["checks"]["tool_correctness"] == "fail"


def test_workflow_order_and_missing_evidence():
    events = trace()
    events[2], events[3] = events[3], events[2]
    assert "node_out_of_order" in codes(evaluate(stamp(events)))
    events = trace()
    events.pop(7)  # no close-round evidence
    report = evaluate(stamp(events))
    assert report["checks"]["ordering"] == "not_assessable"
    assert "missing_node_evidence" in codes(report)


def test_launch_counts_include_failed_qm_and_ignore_cache_hits():
    events = trace()
    events[5]["outputs"]["results"][0].update(status="failed", value=None, error="SCF failed")
    events[5]["outputs"]["results"][1].update(cache_hit=True, electronic_calls_attempted=0)
    events[6]["inputs"]["entries"] = [entry("b", "CCN")]
    events[6]["outputs"]["dataset_size"] = 1
    report = evaluate(events, budgets=dict(BUDGETS, max_qm_calls=0))
    assert report["summary"]["observed_qm_launches"] == 1
    assert "qm_limit_exceeded" in codes(report)
    assert "curated_failed_molecule" not in codes(report)


def test_bad_result_cannot_hide_observed_launches():
    events = trace()
    events[5]["outputs"]["results"][0]["method"] = "dft:PBE0/def2-SVP"
    report = evaluate(events, budgets=dict(BUDGETS, max_qm_calls=1))
    assert report["summary"]["observed_qm_launches"] == 2
    assert "qm_limit_exceeded" in codes(report)
    assert "invalid_tool_call" in codes(report)


def test_unknown_launches_are_not_zero_evidence():
    events = trace()
    del events[5]["outputs"]["results"][0]["electronic_calls_attempted"]
    report = evaluate(events)
    assert report["checks"]["budget_adherence"] == "not_assessable"
    assert report["summary"]["observed_qm_launches"] == 1


def test_wall_time_round_and_dataset_stopping_budgets():
    assert "wall_time_exceeded" in codes(evaluate(trace(), budgets=dict(BUDGETS, max_wall_time=1)))
    events = trace()
    second = copy.deepcopy(events[:9])
    for item in second:
        item["round"] = 2
        item["event_id"] = "second-" + item["event_id"]
    events[8]["outputs"]["continue"] = True
    events = stamp(events[:9] + second + events[9:])
    report = evaluate(events, budgets=dict(BUDGETS, max_rounds=1, target_dataset_size=2))
    assert "round_limit_exceeded" in codes(report)
    assert "generation_after_dataset_target" in codes(report)


def test_step_failure_stops_cleanly_or_flags_continuation():
    events = trace()
    failed = dict(events[2], status="failed", outputs={}, error="tool crashed")
    summary = dict(events[-1], outputs=dict(stop_reason="error"))
    report = evaluate(stamp(events[:2] + [failed, summary]))
    assert report["overall"] == "pass", report["findings"]
    report = evaluate(stamp(events[:2] + [failed] + events[3:]))
    assert "continued_after_tool_failure" in codes(report)
    assert "failure_stop_reason" in codes(report)


def test_per_molecule_failure_can_be_skipped_while_round_continues():
    events = trace()
    events[2]["outputs"]["results"][1].update(status="failed", value=None, xyz_path=None, error="embedding failed")
    events[3]["inputs"]["candidate_ids"] = ["a"]
    events[3]["outputs"]["screened_ids"] = ["a"]
    events[4]["outputs"]["candidate_ids"] = ["a"]
    events[5]["inputs"]["candidate_ids"] = ["a"]
    events[5]["outputs"]["results"] = [quantum("a")]
    events[6]["inputs"]["entries"] = [entry("a", "CCO")]
    events[6]["outputs"]["dataset_size"] = 1
    assert evaluate(events)["overall"] == "pass"


def test_failed_molecule_is_not_curated():
    events = trace()
    events[5]["outputs"]["results"][0].update(status="failed", value=None, error="SCF failed")
    assert "curated_failed_molecule" in codes(evaluate(events))


def test_explicit_failed_retry_and_repeated_success():
    events = trace()
    retry = copy.deepcopy(events[2])
    retry.update(event_id="predict-retry", retry_of_event_id=events[2]["event_id"])
    events[2]["outputs"]["results"][0].update(status="failed", value=None, xyz_path=None, error="failure")
    retry["inputs"]["candidate_ids"] = ["a"]
    retry["outputs"]["results"] = [prediction("a")]
    events.insert(3, retry)
    report = evaluate(stamp(events))
    assert report["overall"] == "pass", report["findings"]
    assert "explicit_failed_retry" in codes(report)
    events = trace()
    duplicate = copy.deepcopy(events[2])
    duplicate.update(event_id="duplicate", retry_of_event_id=events[2]["event_id"])
    events.insert(3, duplicate)
    report = evaluate(stamp(events))
    assert "repeated_molecular_work" in codes(report)
    assert "invalid_retry_reference" in codes(report)


def test_cache_reuse_and_unknown_recipe_repeats():
    events = trace()
    duplicate = copy.deepcopy(events[2])
    duplicate["event_id"] = "cached-predict"
    for result in duplicate["outputs"]["results"]:
        result.update(cache_hit=True, electronic_calls_attempted=0)
    events.insert(3, duplicate)
    report = evaluate(stamp(events))
    assert "repeated_molecular_work" not in codes(report)
    assert "node_out_of_order" in codes(report)  # cached work is still a repeated workflow node
    events = trace()
    events[2]["inputs"].pop("calculation_fingerprints")
    duplicate = copy.deepcopy(events[2]); duplicate["event_id"] = "possible-repeat"
    events.insert(3, duplicate)
    assert "possible_repeated_work" in codes(evaluate(stamp(events)))


def test_cache_claim_with_real_launch_is_invalid():
    events = trace()
    events[5]["outputs"]["results"][0]["cache_hit"] = True
    assert "invalid_cache_accounting" in codes(evaluate(events))


def test_selected_ids_and_qm_method_must_match():
    events = trace()
    events[4]["outputs"]["candidate_ids"] = ["a"]
    assert evaluate(events)["checks"]["tool_correctness"] == "fail"
    events = trace()
    events[5]["outputs"]["results"][0]["method"] = "dft:PBE0/def2-SVP"
    assert evaluate(events)["checks"]["tool_correctness"] == "fail"


def test_ml_and_qm_disabled_path_and_explicit_skip():
    events = trace()
    events = [item for item in events if item["node"] not in ("select_qm_batch", "validate")]
    curated = next(item for item in events if item["node"] == "curate")
    for item in curated["inputs"]["entries"]:
        item.update(validated=False, properties={"xtb": 3.2})
    events.insert(3, event("train", status="skipped", outputs=dict(skip_reason="not enough labels")))
    events.insert(4, event("ml_predict", status="skipped", outputs=dict(skip_reason="no model")))
    assert evaluate(stamp(events), qm_enabled=False, ml_enabled=True)["overall"] == "pass"


def test_train_and_ml_result_contracts():
    events = trace()
    trained = event("train", dict(examples=[dict(smiles="CCO", value=3.2)]),
                    dict(model=dict(model_path="model.json", n_examples=1, metrics={})))
    ml = event("ml_predict", dict(candidate_ids=[]), dict(results=[]))
    events[3:3] = [trained, ml]
    assert evaluate(stamp(events), ml_enabled=True)["overall"] == "pass"
    trained["outputs"]["model"]["n_examples"] = 2
    assert evaluate(stamp(events), ml_enabled=True)["checks"]["tool_correctness"] == "fail"


@pytest.mark.parametrize("change", [dict(trace_version=2), dict(run_id=""), dict(round=0),
    dict(started_at="2026-10-21T00:00:00"), dict(status="unknown"), dict(inputs=None)])
def test_bad_envelopes_are_reported(change):
    events = trace()
    events[0].update(change)
    assert "invalid_event" in codes(evaluate(events))


def test_empty_incomplete_and_duplicate_event_traces():
    assert evaluate([])["overall"] == "not_assessable"
    assert evaluate(trace()[:-1])["checks"]["failure_handling"] == "not_assessable"
    events = trace(); events.insert(1, events[0])
    assert "invalid_event" in codes(evaluate(events))


@pytest.mark.parametrize("key,value", [("max_rounds", True), ("max_qm_calls", -1),
    ("max_wall_time", float("inf")), ("target_dataset_size", 0)])
def test_invalid_budget_configuration(key, value):
    with pytest.raises(ValueError):
        evaluate([], budgets=dict(BUDGETS, **{key: value}))


def test_trace_loader_and_bad_json(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in trace()))
    events, source = load_trace(path)
    assert evaluate(events)["overall"] == "pass"
    assert len(source["sha256"]) == 64
    for bad in ['{"node":"a","node":"b"}', '{"value":NaN}', "[]", "{bad"]:
        path.write_text(bad)
        with pytest.raises(ValueError):
            load_trace(path)


def test_whole_failure_retry_with_missing_result_list_cannot_crash():
    events = trace()
    failed = dict(events[2], status="failed", outputs={"results": None}, error="crash")
    retried = dict(events[2], event_id="bad-retry", retry_of_event_id=failed["event_id"])
    report = evaluate(stamp(events[:2] + [failed, retried] + events[3:]))
    assert "invalid_retry_reference" in codes(report)
    assert "continued_after_tool_failure" in codes(report)


def test_missing_results_are_explicitly_unassessable():
    events = trace()[:3]
    events[2]["outputs"] = {"count": 2}
    events.append(trace()[-1])
    report = evaluate(stamp(events))
    assert "missing_result_evidence" in codes(report)
    assert report["checks"]["tool_correctness"] == "not_assessable"
    assert report["checks"]["repeated_work"] == "not_assessable"


def test_summary_alone_does_not_pass_workflow_checks():
    report = evaluate([trace()[-1]])
    assert report["overall"] == "not_assessable"


def test_model_path_and_training_labels_must_match_evidence():
    events = trace()
    trained = event("train", dict(examples=[dict(smiles="CCO", value=3.2)]),
                    dict(model=dict(model_path="model.json", n_examples=1)))
    ml = event("ml_predict", dict(candidate_ids=["b"], model_path="wrong.json"),
               dict(results=[dict(prediction("b"), xyz_path=None)]))
    events[3:3] = [trained, ml]
    assert "invalid_tool_call" in codes(evaluate(stamp(events), ml_enabled=True))
    trained["inputs"]["examples"][0]["value"] = 10
    assert evaluate(stamp(events), ml_enabled=True)["checks"]["tool_correctness"] == "fail"


def test_changed_recipe_is_not_duplicate_work():
    events = trace()
    repeated = copy.deepcopy(events[2]); repeated["event_id"] = "changed-recipe"
    repeated["inputs"]["calculation_fingerprints"] = {"a": "new-a", "b": "new-b"}
    events.insert(3, repeated)
    report = evaluate(stamp(events))
    assert "repeated_molecular_work" not in codes(report)
    assert "possible_repeated_work" not in codes(report)


def test_no_launch_success_without_cache_is_unknown():
    events = trace()
    events[5]["outputs"]["results"][0]["electronic_calls_attempted"] = 0
    assert "unexplained_zero_launch_success" in codes(evaluate(events))


def two_round_trace(cached=False, repeat=False):
    first = trace()[:-1]
    first[-1]["outputs"]["continue"] = True
    second = copy.deepcopy(trace())
    mapping = {"a": "c", "b": "d"}

    def rename(value):
        if isinstance(value, dict):
            return {mapping.get(key, key): rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    second = rename(second)
    for item in second:
        item["event_id"] = item["event_id"].replace("r1-", "r2-")
        item["round"] = 2
    for item in second[1]["outputs"]["candidates"]:
        item["round"] = 2
        if not (cached or repeat):
            item["smiles"] = "CCCO" if item["id"] == "c" else "CCCN"
    for item in second[6]["inputs"]["entries"]:
        if not (cached or repeat):
            item["smiles"] = "CCCO" if item["id"] == "c" else "CCCN"
    second[6]["outputs"]["dataset_size"] = 4
    if cached:
        for node_index in [2, 5]:
            for item in second[node_index]["outputs"]["results"]:
                item.update(cache_hit=True, electronic_calls_attempted=0)
    return stamp(first + second)


def test_complete_multiround_run_and_cumulative_budgets():
    report = evaluate(two_round_trace())
    assert report["overall"] == "pass", report["findings"]
    assert report["summary"]["observed_qm_launches"] == 4
    assert report["summary"]["rounds"] == 2
    assert report["summary"]["dataset_size"] == 4
    report = evaluate(two_round_trace(), budgets=dict(BUDGETS, max_qm_calls=3))
    assert "qm_limit_exceeded" in codes(report)


def test_multiround_repeat_detection_uses_molecular_identity_not_ids():
    report = evaluate(two_round_trace(repeat=True))
    assert "repeated_molecular_work" in codes(report)
    report = evaluate(two_round_trace(cached=True))
    assert report["overall"] == "pass", report["findings"]
    assert report["summary"]["observed_qm_launches"] == 2


def test_failed_qm_subset_retry_keeps_geometry_and_counts_all_launches():
    events = trace()
    retry = copy.deepcopy(events[5])
    retry.update(event_id="qm-retry", retry_of_event_id=events[5]["event_id"])
    retry["inputs"]["candidate_ids"] = ["a"]
    retry["outputs"]["results"] = [quantum("a")]
    events[5]["outputs"]["results"][0].update(status="failed", value=None, error="SCF failure")
    events.insert(6, retry)
    report = evaluate(stamp(events))
    assert report["overall"] == "pass", report["findings"]
    assert report["summary"]["observed_qm_launches"] == 3
    assert "explicit_failed_retry" in codes(report)


def test_successful_retry_cannot_reuse_a_stale_failure_reference():
    events = trace()
    retry = copy.deepcopy(events[2])
    retry.update(event_id="predict-retry", retry_of_event_id=events[2]["event_id"])
    retry["inputs"]["candidate_ids"] = ["a"]
    retry["outputs"]["results"] = [prediction("a")]
    events[2]["outputs"]["results"][0].update(status="failed", value=None, xyz_path=None, error="failure")
    stale_retry = dict(copy.deepcopy(retry), event_id="stale-retry")
    events[3:3] = [retry, stale_retry]
    findings = evaluate(stamp(events))["findings"]
    assert any(item["code"] == "invalid_retry_reference" and item["event_id"] == "stale-retry" for item in findings)


def test_skipped_validate_cannot_hide_recorded_launches():
    events = trace()
    events[5]["status"] = "skipped"
    events[5]["outputs"]["skip_reason"] = "claimed skip"
    events[6]["inputs"]["entries"] = []
    events[6]["outputs"]["dataset_size"] = 0
    report = evaluate(events, budgets=dict(BUDGETS, max_qm_calls=1))
    assert "invalid_skip" in codes(report)
    assert report["summary"]["observed_qm_launches"] == 2
    assert "qm_limit_exceeded" in codes(report)


@pytest.mark.parametrize("node_index", [2, 5])
def test_missing_results_do_not_invent_downstream_failures(node_index):
    events = trace()
    events[node_index]["outputs"] = {"count": 2}
    report = evaluate(events)
    assert report["overall"] == "not_assessable", report["findings"]
    assert report["checks"]["tool_correctness"] == "not_assessable"


def test_later_round_abort_does_not_mask_earlier_round_missing_nodes():
    events = two_round_trace()
    events = [item for item in events if item["event_id"] != "r1-close_round"]
    failed_index = next(i for i, item in enumerate(events) if item["event_id"] == "r2-predict")
    events[failed_index].update(status="failed", outputs={}, error="crashed")
    summary = events[-1]
    summary["outputs"] = dict(stop_reason="error")
    report = evaluate(stamp(events[:failed_index + 1] + [summary]))
    assert report["checks"]["ordering"] == "not_assessable"
    assert any(item["code"] == "missing_node_evidence" and "round 1" in item["detail"] for item in report["findings"])
