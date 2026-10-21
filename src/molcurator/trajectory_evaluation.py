"""Offline checks for agreed agent-v1 and original provisional traces (issue #13).

This module consumes evidence; it never executes tools or changes agent contracts.
Absent per-molecule or launch evidence yields not_assessable, never an assumed pass.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from rdkit import Chem

from molcurator.schemas import Candidate, CuratedEntry, GenerationSettings, Prediction, QMResult, TrainResult, TrainingExample

CATEGORIES = ("tool_correctness", "ordering", "budget_adherence", "repeated_work", "failure_handling")
ORDER = ("plan_round", "generate", "predict", "train", "ml_predict", "screen",
         "select_qm_batch", "approve_qm", "validate", "curate", "close_round", "continue_or_stop")
OPTIONAL = {"train", "ml_predict", "select_qm_batch", "approve_qm", "validate"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_trace(path: str | Path) -> tuple[list[dict], dict]:
    path = Path(path)
    raw = path.read_bytes()
    events = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line, object_pairs_hook=_object,
                               parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"nonfinite JSON: {s}")))
            if not isinstance(event, dict):
                raise ValueError("trace events must be objects")
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        events.append(event)
    return events, dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamps must be ISO 8601 strings with timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps need timezone")
    return parsed.timestamp()


def _canonical(smiles):
    if not isinstance(smiles, str) or not smiles.strip():
        raise ValueError("nonempty SMILES required")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms():
        raise ValueError("invalid SMILES")
    once = Chem.MolToSmiles(mol)
    again = Chem.MolFromSmiles(once)
    return Chem.MolToSmiles(again) if again is not None else once


def _ids(value):
    if not isinstance(value, list) or any(not isinstance(cid, str) or not cid for cid in value):
        raise ValueError("ordered candidate_ids list required")
    if len(value) != len(set(value)):
        raise ValueError("duplicate candidate IDs in call")
    return value


def _evaluate_provisional(events: list[dict], *, budgets: dict, qm_enabled: bool = True,
                        ml_enabled: bool = False, source: dict | None = None) -> dict:
    """Check one serial run using the documented provisional v1 evidence adapter.

    Budgets have max_rounds, max_qm_calls, max_wall_time, target_dataset_size.
    QM budget counts observed external launches, including failed launches, rather
    than selected IDs. Retries and cache hits must have explicit evidence.
    """
    for key in ("max_rounds", "max_qm_calls", "target_dataset_size"):
        value = budgets.get(key)
        minimum = 0 if key == "max_qm_calls" else 1
        if type(value) is not int or value < minimum:
            raise ValueError(f"{key} must be an integer >= {minimum}")
    wall_limit = budgets.get("max_wall_time")
    if isinstance(wall_limit, bool) or not isinstance(wall_limit, (int, float)) or not math.isfinite(wall_limit) or wall_limit <= 0:
        raise ValueError("max_wall_time must be positive and finite")
    findings = []

    def finding(category, code, detail, event=None, status="fail"):
        findings.append(dict(category=category, status=status, code=code, detail=detail,
                             event_id=event.get("event_id") if isinstance(event, dict) else None))

    registry, stages, values, qm_values, xtb_labels = {}, {}, {}, {}, {}
    unknown_predictions, unknown_validations = set(), set()
    last_result_event = {}
    screened, selected = {}, {}
    event_ids, rounds, completed_events = set(), set(), {}
    work = {}
    launched, unknown_launches, dataset_size = 0, 0, 0
    run_id, previous_end, first_start, last_end = None, None, None, None
    active_model = None
    last_round, abort_event, stop_event, summary_seen = 0, None, None, False
    abort_at = None
    observed_nodes = {}
    mandatory = set(ORDER) - OPTIONAL
    if ml_enabled:
        mandatory |= {"train", "ml_predict"}
    if qm_enabled:
        mandatory |= {"select_qm_batch", "validate"}

    for index, event in enumerate(events, 1):
        try:
            if not isinstance(event, dict) or event.get("trace_version") != 1 or type(event.get("trace_version")) is not int:
                raise ValueError("trace_version=1 required")
            eid, node = event.get("event_id"), event.get("node")
            if not isinstance(eid, str) or not eid or eid in event_ids:
                raise ValueError("unique nonempty event_id required")
            event_ids.add(eid)
            if not isinstance(event.get("run_id"), str) or not event["run_id"]:
                raise ValueError("run_id required")
            if run_id is not None and event["run_id"] != run_id:
                raise ValueError("one run_id per evaluation required")
            run_id = event["run_id"]
            if node not in ORDER and node != "write_summary":
                raise ValueError(f"unknown node: {node}")
            round_number = event.get("round")
            if type(round_number) is not int or round_number < 1:
                raise ValueError("positive integer round required")
            status = event.get("status")
            if status not in ("ok", "failed", "skipped"):
                raise ValueError("status must be ok, failed or skipped")
            inputs, outputs = event.get("inputs"), event.get("outputs")
            if not isinstance(inputs, dict) or not isinstance(outputs, dict):
                raise ValueError("inputs and outputs objects required")
            start, end = _timestamp(event.get("started_at")), _timestamp(event.get("ended_at"))
            if end < start:
                raise ValueError("ended_at precedes started_at")
        except (ValueError, TypeError) as exc:
            finding("tool_correctness", "invalid_event", f"row {index}: {exc}", event)
            # Unknown events may hide work; they prevent a clean budget verdict.
            finding("budget_adherence", "invalid_event_accounting", "Cannot account for malformed event", event, "not_assessable")
            continue

        if summary_seen:
            finding("ordering", "work_after_summary", "Events follow final summary", event)
        if previous_end is not None and start < previous_end:
            finding("ordering", "nonserial_timestamps", "Events overlap or timestamps regress", event)
        previous_end, last_end = end, max(last_end or end, end)
        first_start = start if first_start is None else min(first_start, start)
        if round_number < last_round:
            finding("ordering", "round_regression", "Round number regresses", event)
        if round_number > last_round + 1:
            finding("ordering", "round_gap", "Round sequence has a gap", event)
        last_round = max(last_round, round_number)
        if abort_event and node != "write_summary":
            finding("failure_handling", "continued_after_tool_failure", f"Work follows whole-step failure {abort_event}", event)
        if stop_event and node != "write_summary":
            finding("ordering", "continued_after_stop", f"Work follows stop decision {stop_event}", event)

        if node == "write_summary":
            summary_seen = True
            reason = outputs.get("stop_reason")
            if status != "ok" or not isinstance(reason, str) or not reason:
                finding("failure_handling", "missing_stop_reason", "Successful summary with stop_reason required", event)
            if abort_event and reason != "error":
                finding("failure_handling", "failure_stop_reason", "Whole-step failure requires error stop reason", event)
            continue

        rounds.add(round_number)
        round_nodes = observed_nodes.setdefault(round_number, [])
        prior_rank = max((ORDER.index(name) for name in round_nodes), default=-1)
        retry_ref = event.get("retry_of_event_id")
        retry_source = completed_events.get(retry_ref) if isinstance(retry_ref, str) else None
        source_results = retry_source.get("outputs", {}).get("results") if retry_source else None
        failed_source_ids = {item.get("candidate_id") for item in source_results
                             if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
                             and item.get("status") == "failed"} if isinstance(source_results, list) else set()
        retry_ids = inputs.get("candidate_ids")
        legitimate_retry = bool(retry_source and retry_source["node"] == node
                                and retry_source["round"] == round_number and isinstance(retry_ids, list)
                                and all(isinstance(cid, str) and cid in failed_source_ids for cid in retry_ids)
                                and all(stages.get(cid) == "failed" and last_result_event.get((node, cid)) == retry_ref
                                        for cid in retry_ids)
                                and prior_rank == ORDER.index(node)
                                and retry_ids)
        if retry_ref and not legitimate_retry:
            finding("failure_handling", "invalid_retry_reference", "Retry must reference an earlier same-node/same-round event", event)
        if ORDER.index(node) <= prior_rank and not legitimate_retry:
            finding("ordering", "node_out_of_order", "Node repeats or moves backwards within the round", event)
        round_nodes.append(node)
        if round_number > budgets["max_rounds"]:
            finding("budget_adherence", "round_limit_exceeded", "Round exceeds max_rounds", event)
        if node == "generate" and dataset_size >= budgets["target_dataset_size"]:
            finding("budget_adherence", "generation_after_dataset_target", "New generation after dataset target was reached", event)

        # Account for observed work independently of whether the call/results pass
        # correctness checks. A malformed result must not hide an expensive launch.
        recorded_work = bool(outputs.get("results")) or outputs.get("electronic_calls_attempted") not in (None, 0)
        if node == "validate" and (status != "skipped" or recorded_work):
            raw_launch_results = outputs.get("results")
            if isinstance(raw_launch_results, list):
                for item in raw_launch_results:
                    count = item.get("electronic_calls_attempted") if isinstance(item, dict) else None
                    if type(count) is int and count in (0, 1):
                        launched += count
                    else:
                        unknown_launches += 1
                expected = inputs.get("candidate_ids")
                if not isinstance(expected, list) or len(expected) != len(raw_launch_results):
                    unknown_launches += 1
            elif status in ("failed", "skipped") and type(outputs.get("electronic_calls_attempted")) is int and outputs["electronic_calls_attempted"] >= 0:
                launched += outputs["electronic_calls_attempted"]
            else:
                unknown_launches += 1

        if status == "failed":
            if not isinstance(event.get("error"), str) or not event["error"].strip():
                finding("failure_handling", "missing_step_error", "Whole-step failure needs error text", event)
            if abort_event is None:
                abort_event = eid
                abort_at = (round_number, ORDER.index(node))
            completed_events[eid] = event
            continue
        if status == "skipped":
            if node not in OPTIONAL or not isinstance(outputs.get("skip_reason"), str) or not outputs["skip_reason"].strip():
                finding("tool_correctness", "invalid_skip", "Only optional steps may skip, with a reason", event)
            if node == "validate" and recorded_work:
                finding("tool_correctness", "invalid_skip", "Skipped validation contains recorded work", event)
            completed_events[eid] = event
            continue

        try:
            if node == "generate":
                parents = inputs.get("parents")
                if not isinstance(parents, list) or not parents:
                    raise ValueError("generate needs parent SMILES")
                parent_smiles = {_canonical(parent) for parent in parents}
                settings = GenerationSettings.model_validate(inputs.get("settings"))
                candidates = outputs.get("candidates")
                if not isinstance(candidates, list):
                    raise ValueError("full generated candidates required")
                if len(candidates) > settings.n_candidates:
                    raise ValueError("generator exceeded requested candidate count")
                for raw in candidates:
                    candidate = Candidate.model_validate(raw)
                    canonical = _canonical(candidate.smiles)
                    if candidate.id in registry:
                        raise ValueError(f"generated ID reused: {candidate.id}")
                    if candidate.round != round_number or candidate.generator != settings.generator:
                        raise ValueError("candidate round/generator differs from call")
                    if _canonical(candidate.parent_smiles) not in parent_smiles:
                        raise ValueError("candidate parent was not supplied to generator")
                    registry[candidate.id] = dict(smiles=canonical, round=round_number)
                    stages[candidate.id] = "generated"
            elif node in ("predict", "ml_predict", "validate"):
                ids = _ids(inputs.get("candidate_ids"))
                if any(cid not in registry for cid in ids):
                    raise ValueError("tool input contains unknown candidate ID")
                if node == "validate":
                    if not qm_enabled:
                        raise ValueError("QM called while disabled")
                    approved = selected.get(round_number)
                    matches_batch = ids == approved
                    if legitimate_retry and approved is not None:
                        matches_batch = ids == [cid for cid in approved if cid in ids]
                    if not matches_batch:
                        raise ValueError("QM input does not match selected/approved batch")
                if node == "ml_predict" and not ml_enabled:
                    raise ValueError("ML called while disabled")
                if node == "ml_predict" and ids and (active_model is None or inputs.get("model_path") != active_model):
                    raise ValueError("ML call needs the current trained model_path")
                raw_results = outputs.get("results")
                if not isinstance(raw_results, list):
                    finding("tool_correctness", "missing_result_evidence", "Ordered per-molecule results required", event, "not_assessable")
                    finding("repeated_work", "missing_work_evidence", "Cannot compare work without per-molecule results", event, "not_assessable")
                    finding("failure_handling", "missing_failure_evidence", "Per-molecule statuses missing", event, "not_assessable")
                    unknown = unknown_validations if node == "validate" else unknown_predictions
                    unknown.update(ids)
                    for cid in ids:
                        stages[cid] = "unknown"
                    continue
                if [item.get("candidate_id") if isinstance(item, dict) else None for item in raw_results] != ids:
                    raise ValueError("results must match input IDs exactly once and in order")
                for cid, raw in zip(ids, raw_results):
                    model = QMResult if node == "validate" else Prediction
                    result = model.model_validate(raw)
                    if result.value is not None and not math.isfinite(result.value):
                        raise ValueError("successful results must be finite")
                    if result.status.value == "ok" and result.error:
                        raise ValueError("successful result carries an error")
                    if node == "validate":
                        if cid in unknown_predictions:
                            finding("tool_correctness", "missing_qm_input_evidence", f"{cid} prediction evidence is unavailable", event, "not_assessable")
                        elif not values.get(cid, {}).get("xyz_path") or (stages.get(cid) == "failed" and not legitimate_retry):
                            finding("failure_handling", "ineligible_qm_input", f"{cid} lacks successful geometry-bearing prediction", event)
                    if node == "validate":
                        expected_method = inputs.get("qm_method")
                        if not isinstance(expected_method, str):
                            finding("tool_correctness", "missing_qm_method", "Requested QM method required", event, "not_assessable")
                        elif result.method != expected_method:
                            raise ValueError("QM method differs from requested method")
                        qm_values[cid] = result
                    if stages.get(cid) == "failed" and not legitimate_retry:
                        finding("failure_handling", "failed_molecule_reused", f"{cid} reused without explicit retry", event)
                    if node == "predict" and result.status.value == "ok" and not result.xyz_path:
                        raise ValueError("successful xTB prediction requires XYZ path")
                    if node == "ml_predict" and result.xyz_path is not None:
                        raise ValueError("ML prediction must not claim a geometry")
                    count, cached = raw.get("electronic_calls_attempted"), raw.get("cache_hit")
                    if "cache_hit" in raw and type(cached) is not bool:
                        raise ValueError("cache_hit must be boolean")
                    if cached is True and count != 0:
                        finding("repeated_work", "invalid_cache_accounting", "Cache hit requires zero launches", event)
                    if node == "validate" and result.status.value == "ok" and count == 0 and cached is not True:
                        finding("budget_adherence", "unexplained_zero_launch_success", "Zero-launch QM success needs explicit cache evidence", event, "not_assessable")
                    fingerprint = inputs.get("calculation_fingerprints", {}).get(cid) if isinstance(inputs.get("calculation_fingerprints", {}), dict) else None
                    if fingerprint is not None and (not isinstance(fingerprint, str) or not fingerprint):
                        raise ValueError("calculation fingerprints must be nonempty strings")
                    key = (node, registry[cid]["smiles"], result.method if node == "validate" else None, fingerprint)
                    previous = work.get(key)
                    if previous and cached is not True:
                        if legitimate_retry and previous["status"] == "failed" and previous["event_id"] == retry_ref:
                            finding("repeated_work", "explicit_failed_retry", f"Retry of failed work for {cid}", event, "pass")
                        else:
                            finding("repeated_work", "repeated_molecular_work" if fingerprint else "possible_repeated_work",
                                    f"{cid} repeats {previous['event_id']}; canonical molecule and method match", event,
                                    "fail" if fingerprint else "not_assessable")
                    work[key] = dict(event_id=eid, status=result.status.value)
                    if node != "validate":
                        values[cid] = dict(value=result.value, xyz_path=str(result.xyz_path) if result.xyz_path else None)
                    if node == "predict" and result.status.value == "ok":
                        xtb_labels[registry[cid]["smiles"]] = result.value
                    (unknown_validations if node == "validate" else unknown_predictions).discard(cid)
                    last_result_event[(node, cid)] = eid
                    stages[cid] = "failed" if result.status.value == "failed" else node
                if node == "validate" and any(type(item.get("electronic_calls_attempted")) is not int for item in raw_results):
                    finding("budget_adherence", "unknown_qm_launches", "Per-item launch counts missing", event, "not_assessable")
            elif node == "train":
                if not ml_enabled:
                    raise ValueError("TRAIN called while ML disabled")
                examples = inputs.get("examples")
                if not isinstance(examples, list) or not examples:
                    raise ValueError("training examples required")
                for example in examples:
                    parsed = TrainingExample.model_validate(example)
                    if not math.isfinite(parsed.value):
                        raise ValueError("nonfinite training label")
                    if xtb_labels.get(_canonical(parsed.smiles)) != parsed.value:
                        raise ValueError("training label has no matching successful xTB evidence")
                trained = TrainResult.model_validate(outputs.get("model"))
                if trained.n_examples != len(examples):
                    raise ValueError("training example count mismatch")
                if any(not math.isfinite(value) for value in trained.metrics.values()):
                    raise ValueError("nonfinite training metric")
                active_model = str(trained.model_path)
            elif node == "screen":
                ids = _ids(inputs.get("candidate_ids"))
                if any(stages.get(cid) not in ("predict", "ml_predict") and cid not in unknown_predictions for cid in ids):
                    raise ValueError("screen requires successful predictions")
                if any(cid in unknown_predictions for cid in ids):
                    finding("tool_correctness", "missing_screen_input_evidence", "Screen inputs have unknown prediction outcomes", event, "not_assessable")
                kept = _ids(outputs.get("screened_ids"))
                if not set(kept) <= set(ids):
                    raise ValueError("screen contains unknown or unscored candidates")
                screened[round_number] = kept
            elif node in ("select_qm_batch", "approve_qm"):
                pool = screened.get(round_number, []) if node == "select_qm_batch" else selected.get(round_number, [])
                ids = _ids(outputs.get("candidate_ids"))
                if not set(ids) <= set(pool):
                    raise ValueError("selected/approved IDs are not an eligible subset")
                selected[round_number] = ids
            elif node == "curate":
                entries = inputs.get("entries")
                if not isinstance(entries, list):
                    raise ValueError("curated entries required")
                entry_ids = []
                for raw in entries:
                    entry = CuratedEntry.model_validate(raw)
                    if any(not math.isfinite(value) for value in entry.properties.values()):
                        raise ValueError("nonfinite curated property")
                    entry_ids.append(entry.id)
                    if entry.id not in registry or _canonical(entry.smiles) != registry[entry.id]["smiles"]:
                        raise ValueError("curated identity does not match generated molecule")
                    if stages[entry.id] == "failed":
                        finding("failure_handling", "curated_failed_molecule", f"{entry.id} was failed", event)
                    if qm_enabled and (not entry.validated or (stages[entry.id] != "validate" and entry.id not in unknown_validations)):
                        raise ValueError("QM-mode curation needs successful validation")
                    if qm_enabled and entry.id in unknown_validations:
                        finding("tool_correctness", "missing_curation_validation_evidence", f"{entry.id} validation outcome is unknown", event, "not_assessable")
                    elif qm_enabled:
                        qm_result = qm_values[entry.id]
                        if entry.properties.get(qm_result.method) != qm_result.value:
                            raise ValueError("curated QM property differs from validation evidence")
                    if not qm_enabled and entry.id not in screened.get(round_number, []):
                        raise ValueError("ML/xTB-mode curation needs screened-in candidate")
                _ids(entry_ids)
                size = outputs.get("dataset_size")
                if type(size) is not int or not dataset_size <= size <= dataset_size + len(entries):
                    raise ValueError("invalid cumulative dataset size")
                dataset_size = size
            elif node == "continue_or_stop":
                if type(outputs.get("continue")) is not bool:
                    raise ValueError("explicit boolean continue decision required")
                if outputs["continue"] is False:
                    stop_event = eid
        except (ValueError, TypeError, KeyError) as exc:
            finding("tool_correctness", "invalid_tool_call", str(exc), event)
        completed_events[eid] = event

    if not events or not observed_nodes:
        for category in CATEGORIES:
            finding(category, "empty_trace" if not events else "missing_workflow_evidence",
                    "No workflow nodes supplied", status="not_assessable")
    if not summary_seen:
        finding("failure_handling", "missing_final_summary", "Run may be incomplete; no final summary", status="not_assessable")
    for number, nodes in observed_nodes.items():
        required = mandatory
        if abort_at is not None and number == abort_at[0]:
            required = {node for node in mandatory if ORDER.index(node) <= abort_at[1]}
        missing = required - set(nodes)
        if missing:
            finding("ordering", "missing_node_evidence", f"round {number}: {sorted(missing)}", status="not_assessable")
    if launched > budgets["max_qm_calls"]:
        finding("budget_adherence", "qm_limit_exceeded", f"Observed {launched} QM launches exceed limit")
    if unknown_launches:
        finding("budget_adherence", "incomplete_qm_accounting", "QM launch count is a lower bound", status="not_assessable")
    elapsed = last_end - first_start if first_start is not None else None
    if elapsed is not None and elapsed > wall_limit:
        finding("budget_adherence", "wall_time_exceeded", f"Observed trace span {elapsed}s exceeds limit")
    checks = {}
    for category in CATEGORIES:
        statuses = [item["status"] for item in findings if item["category"] == category]
        checks[category] = "fail" if "fail" in statuses else "not_assessable" if "not_assessable" in statuses else "pass"
    overall = "fail" if "fail" in checks.values() else "not_assessable" if "not_assessable" in checks.values() else "pass"
    return dict(report_version=1, metadata=dict(trace_contract="provisional-v1", coordination_issue=13,
                source=source, run_id=run_id, budgets=dict(budgets), qm_enabled=qm_enabled, ml_enabled=ml_enabled),
                overall=overall, checks=checks, findings=findings,
                summary=dict(events=len(events), rounds=len(rounds), candidates=len(registry),
                             observed_qm_launches=launched, unknown_qm_events=unknown_launches,
                             elapsed_s=elapsed, dataset_size=dataset_size,
                             finding_counts=dict(Counter(item["code"] for item in findings))))


def evaluate_trajectory(events: list[dict], *, budgets: dict | None = None,
                        qm_enabled: bool | None = None, ml_enabled: bool | None = None,
                        source: dict | None = None, trace_format: str = "auto") -> dict:
    """Read agreed agent-v1 traces or retain the original provisional interface.

    Agent-v1 policy defaults come from run_start. Explicit budget overrides are
    recorded, while conflicting execution-mode overrides are rejected.
    """
    if trace_format not in ("auto", "agent-v1", "provisional-v1"):
        raise ValueError("trace_format must be auto, agent-v1 or provisional-v1")
    def is_compact(event):
        if not isinstance(event, dict):
            return False
        if event.get("node") == "run_start":
            return True
        outputs = event.get("outputs")
        results = outputs.get("results") if isinstance(outputs, dict) else None
        return isinstance(results, list) and any(isinstance(row, list) for row in results)
    compact = any(is_compact(event) for event in events)
    if trace_format == "agent-v1" or (trace_format == "auto" and compact):
        from molcurator.trace_v1_evaluation import evaluate_agent_v1
        return evaluate_agent_v1(events, budgets=budgets, qm_enabled=qm_enabled,
                                 ml_enabled=ml_enabled, source=source)
    if budgets is None:
        raise ValueError("provisional traces require explicit budgets")
    report = _evaluate_provisional(events, budgets=budgets,
        qm_enabled=True if qm_enabled is None else qm_enabled,
        ml_enabled=False if ml_enabled is None else ml_enabled, source=source)
    enabled = report["metadata"]["qm_enabled"]
    report["capabilities"] = {"qm_behavior": {
        "status": "not_measurable" if not enabled else "available",
        "label": "QM behavior: not measurable" if not enabled else "QM behavior: evaluated from supplied evidence",
        "reason": "QM disabled" if not enabled else "Provisional per-item evidence; see findings"}}
    return report
