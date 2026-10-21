"""Reader for docs/trace-format.md at agent commit 84fe9ec (issue #13).

Compact rows describe changed state, not full tool returns. Never fabricate
geometries, raw return order, QM launches, or model provenance from those rows.
"""
from __future__ import annotations

import math
from collections import Counter

from molcurator.schemas import GenerationSettings, TrainResult
from molcurator.trajectory_evaluation import CATEGORIES, _canonical, _ids, _timestamp

SUPPORTED = {"plan_round", "generate", "predict", "train", "ml_predict", "screen",
             "curate", "close_round", "continue_or_stop", "write_summary"}
QM_NODES = {"select_qm_batch", "approve_qm", "validate"}
STOP_REASONS = {"target_dataset_size", "max_rounds", "max_qm_calls", "max_wall_time", "llm", "error"}
STATES = {"generate": {"generated", "duplicate"}, "predict": {"predicted", "failed"},
          "ml_predict": {"ml_predicted", "failed", "unscored"},
          "screen": {"screened_in", "screened_out"}, "curate": {"curated"}}


def _number(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)
    except OverflowError:
        return False


def _capability(label, reason):
    return dict(status="not_measurable", label=f"{label}: not measurable", reason=reason)


def evaluate_agent_v1(events, *, budgets=None, qm_enabled=None, ml_enabled=None, source=None):
    findings = []

    def note(category, code, detail, event=None, status="fail"):
        findings.append(dict(category=category, status=status, code=code, detail=detail,
                             event_id=event.get("event_id") if isinstance(event, dict) and isinstance(event.get("event_id"), str) else None))

    header = events[0] if events and isinstance(events[0], dict) and events[0].get("node") == "run_start" else None
    header_inputs = header.get("inputs") if header else None
    config = header_inputs.get("config", {}) if isinstance(header_inputs, dict) else {}
    config = config if isinstance(config, dict) else {}
    for section in ("qm", "predict", "train", "screening", "target", "generation", "budget"):
        if section in config and not isinstance(config[section], dict):
            raise ValueError(f"run_start config {section} must be an object")
    nodes = header_inputs.get("nodes") if isinstance(header_inputs, dict) else None
    declared = nodes if isinstance(nodes, list) and nodes and all(isinstance(n, str) for n in nodes) else []
    policy = dict(config.get("budget", {})) if isinstance(config.get("budget"), dict) else {}
    policy.update(budgets or {})
    for key, value in policy.items():
        if key in ("max_rounds", "max_qm_calls", "target_dataset_size"):
            if type(value) is not int or value < (0 if key == "max_qm_calls" else 1):
                raise ValueError(f"{key}: invalid budget")
        if key == "max_wall_time" and (not _number(value) or value <= 0):
            raise ValueError("max_wall_time must be positive and finite")
    qm_config = config.get("qm", {})
    recorded_qm = qm_config.get("enabled") if isinstance(qm_config, dict) else None
    if recorded_qm is not None and type(recorded_qm) is not bool:
        raise ValueError("run_start config qm.enabled must be boolean")
    if qm_enabled is not None and recorded_qm is not None and qm_enabled != recorded_qm:
        raise ValueError("QM mode override conflicts with recorded config")
    qm = recorded_qm if recorded_qm is not None else qm_enabled
    ml = any(n in declared for n in ("train", "ml_predict"))
    if ml_enabled is not None and declared and ml_enabled != ml:
        raise ValueError("ML mode override conflicts with recorded graph")
    capabilities = {
        "qm_behavior": _capability("QM behavior", "QM disabled" if qm is False else "QM behavior is not defined by agent trace v1"),
        "qm_launch_accounting": _capability("QM launch accounting", "No per-item launch/cache evidence in v1"),
        "llm_behavior": _capability("LLM behavior", "v1 covers rules-only decisions; rule metadata is checked separately"),
        "rule_decision_metadata": _capability("Rule decision metadata", "No rule metadata observed"),
        "tool_return_order": _capability("Original tool return order", "Rows are sorted by the writer after tool execution"),
        "geometry_handoff": _capability("Geometry handoff", "Compact rows contain no XYZ paths"),
        "training_provenance": _capability("Training provenance", "Training input identities/model fingerprints are absent"),
        "generation_lineage": _capability("Per-molecule parent lineage", "Only round-level parent IDs are recorded"),
        "recipe_reuse": _capability("Recipe/cache reuse", "No calculation/model fingerprints or cache evidence in v1"),
        "resume": _capability("Resume behavior", "Resume event identity is explicitly outside v1"),
    }
    registry, seen_structures, work = {}, set(), set()
    model = None
    size, last_size, maximum_round = 0, 0, 0
    first_start, last_end, previous_end = None, None, None
    seen_events, seen_rounds, round_nodes = set(), set(), {}
    failed_step, summary_seen, stopped, stop_reason = None, False, False, None
    reported_qm_calls = 0
    unknown_states = set()
    prediction_calls = {}
    recorded_decisions = 0
    structurally_identified = 0
    plans = {}
    unknown_size = False
    incomplete_effects = False

    def report():
        if recorded_decisions:
            invalid = any(f["code"] in ("invalid_decision_metadata", "invalid_rule_metadata") for f in findings)
            capabilities["rule_decision_metadata"] = dict(status="fail" if invalid else "evaluated",
                label="Rule decision metadata: failed" if invalid else "Rule decision metadata: passed",
                reason=f"{recorded_decisions} recorded rule decisions; not an LLM execution claim")
        checks = {}
        for category in CATEGORIES:
            statuses = [f["status"] for f in findings if f["category"] == category]
            checks[category] = "fail" if "fail" in statuses else "not_assessable" if "not_assessable" in statuses else "pass"
        overall = "fail" if "fail" in checks.values() else "not_assessable" if "not_assessable" in checks.values() else "pass"
        return dict(report_version=1, metadata=dict(trace_contract="agent-v1", contract_status="work_in_progress",
            specification="docs/trace-format.md@84fe9ec", overall_scope="available_evidence_only",
            coordination_issue=13, source=source, run_id=header.get("run_id") if header else None,
            budgets=policy, budget_overrides=dict(budgets or {}), qm_enabled=qm, ml_enabled=ml),
            overall=overall, checks=checks, capabilities=capabilities, findings=findings,
            summary=dict(events=len(events), rounds=len(seen_rounds), candidates=len(registry),
                molecular_identities_available=structurally_identified, dataset_size=None if unknown_size else size,
                observed_qm_launches=None, reported_qm_calls=reported_qm_calls,
                elapsed_s=last_end - first_start if first_start is not None else None,
                recorded_rule_decisions=recorded_decisions, stop_reason=stop_reason,
                finding_counts=dict(Counter(f["code"] for f in findings))))

    if header is None:
        for category in CATEGORIES:
            note(category, "missing_run_start", "Agent v1 needs run_start config and node order", status="not_assessable")
        return report()
    if any(isinstance(e, dict) and e.get("node") == "run_start" and e.get("resumed") is True for e in events):
        for category in CATEGORIES:
            note(category, "unsupported_resume", "Resume format is not settled in v1", status="not_assessable")
        return report()
    if not declared or len(set(declared)) != len(declared) or declared[-1] != "write_summary" or "run_start" in declared:
        note("ordering", "invalid_declared_graph", "run_start.inputs.nodes needs unique nodes ending in write_summary", header)
    if not config:
        note("tool_correctness", "missing_run_config", "Full run config unavailable", header, "not_assessable")
    required_budgets = {"max_rounds", "max_qm_calls", "max_wall_time", "target_dataset_size"}
    if not required_budgets <= policy.keys():
        note("budget_adherence", "missing_budget_evidence", "Run limits unavailable", header, "not_assessable")
    if qm is None:
        note("tool_correctness", "unknown_qm_mode", "qm.enabled unavailable", header, "not_assessable")
    if qm is True:
        note("tool_correctness", "unsupported_qm_behavior", "QM execution is not covered by agent v1", header, "not_assessable")
        note("budget_adherence", "unavailable_qm_accounting", "Cannot verify QM launches from round counters", header, "not_assessable")
    for seed in config.get("seeds", []) if isinstance(config.get("seeds", []), list) else []:
        try:
            seen_structures.add(_canonical(seed))
        except ValueError:
            note("repeated_work", "unavailable_seed_identity", "Seed molecular identity is unavailable", header, "not_assessable")

    def inside(value, margin=0):
        target = config.get("target", {})
        if not isinstance(target, dict) or not _number(value):
            return None
        low, high = target.get("min"), target.get("max")
        if low is None and high is None or any(bound is not None and not _number(bound) for bound in (low, high)):
            return None
        return (low is None or value >= low - margin - 1e-9) and (high is None or value <= high + margin + 1e-9)

    for index, event in enumerate(events):
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            if type(event.get("trace_version")) is not int or event["trace_version"] != 1:
                note("tool_correctness", "unsupported_trace_version", "Only documented trace v1 is supported", event, "not_assessable")
                continue
            required = {"run_id", "event_id", "node", "round", "started_at", "ended_at", "status", "reason", "error", "inputs", "outputs"}
            if not required <= event.keys():
                raise ValueError(f"missing envelope keys: {sorted(required - event.keys())}")
            node, rnd, eid = event["node"], event["round"], event["event_id"]
            if not isinstance(node, str) or not isinstance(event["run_id"], str) or not event["run_id"] or event["run_id"] != header["run_id"]:
                raise ValueError("inconsistent run_id or invalid node")
            expected_id = f"{event['run_id']}:run_start" if node == "run_start" else f"{event['run_id']}:r{rnd}:{node}"
            if eid != expected_id or eid in seen_events:
                raise ValueError("invalid or duplicate event_id")
            seen_events.add(eid)
            if node == "run_start":
                if index != 0 or rnd is not None or event.get("resumed") is not False:
                    raise ValueError("new run_start must be first, round null, resumed false")
            elif type(rnd) is not int or rnd < 1:
                raise ValueError("positive integer round required")
            status, inputs, outputs = event["status"], event["inputs"], event["outputs"]
            if status not in ("ok", "failed", "skipped") or not isinstance(inputs, dict) or not isinstance(outputs, dict):
                raise ValueError("invalid status/inputs/outputs")
            start, end = _timestamp(event["started_at"]), _timestamp(event["ended_at"])
            if end < start:
                raise ValueError("ended_at precedes started_at")
        except (ValueError, TypeError, KeyError) as exc:
            note("tool_correctness", "invalid_event", str(exc), event)
            note("budget_adherence", "invalid_event_accounting", "Malformed event hides timing/work evidence", event, "not_assessable")
            continue
        if previous_end is not None and start < previous_end:
            note("ordering", "nonserial_timestamps", "Event timestamps overlap or regress", event)
        first_start = start if first_start is None else min(start, first_start)
        last_end, previous_end = max(last_end if last_end is not None else end, end), end
        if node == "run_start":
            if status != "ok":
                note("tool_correctness", "invalid_run_start", "run_start must succeed", event)
            continue
        if summary_seen or stopped and node != "write_summary":
            note("ordering", "work_after_stop", "Work follows summary or stop decision", event)
        if failed_step and node != "write_summary":
            note("failure_handling", "continued_after_tool_failure", "Whole-step failure must route straight to summary", event)
        if rnd < maximum_round or rnd > maximum_round + 1:
            note("ordering", "round_sequence", "Rounds regress or have gaps", event)
        maximum_round = max(maximum_round, rnd)
        if node != "write_summary":
            seen_rounds.add(rnd)
            observed = round_nodes.setdefault(rnd, [])
            if node not in declared:
                note("ordering", "undeclared_node", "Node absent from declared graph", event)
            elif any(n in declared and declared.index(n) >= declared.index(node) for n in observed):
                note("ordering", "node_out_of_order", "Node violates run_start declared order", event)
            observed.append(node)
        if node in QM_NODES:
            note("tool_correctness", "qm_called_while_disabled" if qm is False else "unsupported_qm_node",
                 "QM nodes are not defined by v1", event, "fail" if qm is False else "not_assessable")
            continue
        if node not in SUPPORTED:
            note("tool_correctness", "unsupported_node", f"No v1 evidence reader for {node}", event, "not_assessable")
            continue
        if rnd > policy.get("max_rounds", rnd):
            note("budget_adherence", "round_limit_exceeded", "Round exceeds configured limit", event)
        if node == "generate" and not unknown_size and size >= policy.get("target_dataset_size", size + 1):
            note("budget_adherence", "generation_after_dataset_target", "Generation continued after target size", event)
        if status == "failed":
            if not isinstance(event["error"], str) or not event["error"].startswith(f"{node}: "):
                note("failure_handling", "missing_step_error", "Failed line must name node and error", event)
            failed_step = failed_step or (rnd, node)
            continue
        if event["error"] is not None:
            note("failure_handling", "contradictory_step_error", "Nonfailed line carries error", event)
        llm = event.get("llm")
        if llm is not None:
            if not isinstance(llm, dict):
                note("tool_correctness", "invalid_decision_metadata", "llm must be an object", event)
            elif llm.get("source") == "rule":
                recorded_decisions += 1
                if not {"decision", "source", "fallback", "retried", "prompt", "raw_response", "duration_s"} <= llm.keys() or type(llm.get("retried")) is not bool or not _number(llm.get("duration_s")) or llm["duration_s"] < 0:
                    note("tool_correctness", "invalid_decision_metadata", "Decision metadata fields/types are invalid", event)
                if config.get("decisions") == "rules" and (llm.get("fallback") != "rules_mode" or llm.get("prompt") is not None or llm.get("raw_response") is not None):
                    note("tool_correctness", "invalid_rule_metadata", "Rules mode must declare rules_mode with no prompt/response", event)
            else:
                note("tool_correctness", "unsupported_llm_behavior", "Live LLM behavior is outside v1", event, "not_assessable")
        if status == "skipped":
            allowed = {"train": "below_min_examples", "ml_predict": "no_candidates_left"}
            if node not in allowed or event["reason"] != allowed[node]:
                note("tool_correctness", "unsupported_skip_reason", "Skip is not documented for this node", event, "not_assessable")
            if outputs:
                note("tool_correctness", "invalid_skip", "Skipped v1 node must have no changed outputs", event)
            if node == "train":
                successful = sum(m.get("xtb") is not None for m in registry.values())
                minimum = config.get("train", {}).get("min_examples")
                if type(minimum) is int and successful >= minimum:
                    note("tool_correctness", "invalid_train_skip", "Enough xTB labels were present for TRAIN", event)
            if node == "ml_predict":
                if any(m["state"] == "generated" and cid not in unknown_states for cid, m in registry.items()):
                    note("tool_correctness", "invalid_ml_skip", "Unscored generated candidates remain", event)
                elif unknown_states:
                    note("tool_correctness", "unavailable_ml_skip_inputs", "Cannot verify skip against missing prediction effects", event, "not_assessable")
            continue
        if event["reason"] is not None:
            note("tool_correctness", "unexpected_skip_reason", "Only skipped lines carry reason", event)
        try:
            if node == "plan_round":
                plan = outputs.get("round_plan")
                if not isinstance(plan, dict) or not isinstance(plan.get("parents"), list) or not plan["parents"] or not all(isinstance(p, str) and p for p in plan["parents"]):
                    raise ValueError("round_plan needs parent IDs")
                settings = GenerationSettings.model_validate({k: plan[k] for k in ("generator", "n_candidates", "mutation_strength")})
                limits = config.get("generation", {})
                if settings.n_candidates > limits.get("max_candidates", 1000) or settings.mutation_strength > limits.get("max_mutation_strength", 5) or settings.generator not in limits.get("generators", [settings.generator]):
                    raise ValueError("round plan exceeds recorded generation limits")
                if not isinstance(plan.get("reason"), str) or not plan["reason"].strip():
                    raise ValueError("round plan needs reason")
                plans[rnd] = plan
            elif node in STATES:
                raw_results = outputs.get("results", [])
                ids = _ids(inputs.get("candidate_ids", [])) if node != "generate" else []
                if node == "predict":
                    prediction_calls[rnd] = len(ids)
                if not isinstance(raw_results, list):
                    raise ValueError("results must be compact row list")
                if not ids and not raw_results and node in ("predict", "ml_predict", "screen", "curate"):
                    eligible = [cid for cid, item in registry.items() if
                        (node in ("predict", "ml_predict") and item["state"] == "generated") or
                        (node == "screen" and item["state"] in ("predicted", "ml_predicted")) or
                        (node == "curate" and item["state"] == "screened_in" and inside(item["value"]) is True)]
                    if eligible:
                        incomplete_effects = True
                        note("tool_correctness", "unavailable_node_effects", f"{node}: eligible molecules but no recorded effects", event, "not_assessable")
                        unknown_states.update(eligible)
                        if node == "curate":
                            unknown_size = True
                if ids and not raw_results:
                    incomplete_effects = True
                    note("tool_correctness", "missing_result_evidence", "Called IDs have no changed-state rows", event, "not_assessable")
                    unknown_states.update(ids)
                    continue
                rows = []
                for row in raw_results:
                    if not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str) or row[1] not in STATES[node]:
                        raise ValueError("expected [candidate_id, node_status, value_or_error]")
                    cid, state, value = row
                    if state == "failed" and (not isinstance(value, str) or not value.strip()):
                        raise ValueError("failed result needs error text")
                    if state not in ("failed", "unscored") and node in ("predict", "ml_predict") and not _number(value):
                        raise ValueError("prediction must be finite numeric value")
                    if (node in ("screen", "curate") or state == "unscored") and value is not None:
                        raise ValueError("state-only result must have null value")
                    rows.append((cid, state, value))
                row_ids = _ids([row[0] for row in rows])
                if row_ids != sorted(row_ids):
                    raise ValueError("compact results must be sorted by candidate ID")
                if node != "generate" and row_ids != sorted(ids):
                    raise ValueError("changed-state IDs differ from declared input IDs")
                if node == "generate":
                    plan = inputs.get("round_plan")
                    if not isinstance(plan, dict):
                        raise ValueError("generate needs round_plan")
                    if rnd in plans and plan != plans[rnd]:
                        raise ValueError("generate round_plan differs from recorded decision")
                    settings = GenerationSettings.model_validate({k: plan[k] for k in ("generator", "n_candidates", "mutation_strength")})
                    if len(rows) > settings.n_candidates:
                        raise ValueError("more generated records than requested")
                    for cid, state, smiles in rows:
                        if cid in registry or not isinstance(smiles, str) or not smiles:
                            raise ValueError("reused ID or missing generated SMILES")
                        try:
                            canonical = _canonical(smiles)
                            structurally_identified += 1
                        except ValueError:
                            canonical = None
                            note("repeated_work", "unavailable_molecular_identity", f"{cid}: SMILES cannot establish identity (e.g. fake-tool placeholder)", event, "not_assessable")
                        if canonical and (canonical in seen_structures) != (state == "duplicate"):
                            raise ValueError("duplicate status disagrees with known molecular identity")
                        if canonical:
                            seen_structures.add(canonical)
                        registry[cid] = dict(state=state, original_state=state, round=rnd, canonical=canonical,
                                             value=None, xtb=None, ml=None)
                else:
                    if any(cid not in registry for cid in row_ids):
                        raise ValueError("unknown molecule ID")
                    if node == "predict":
                        limit = config.get("predict", {}).get("n_xtb")
                        if type(limit) is int and len(ids) > limit:
                            raise ValueError("xTB sample exceeds predict.n_xtb")
                        if ids != sorted(ids):
                            raise ValueError("PREDICT input sample must be in ID order")
                    for cid, state, value in rows:
                        item = registry[cid]
                        previous = item["state"]
                        if cid in unknown_states:
                            note("tool_correctness", "unavailable_input_state", f"{cid}: earlier state evidence unavailable", event, "not_assessable")
                        elif node in ("predict", "ml_predict") and previous != "generated":
                            raise ValueError("only newly generated nonduplicate molecules can be predicted")
                        elif node == "screen" and previous not in ("predicted", "ml_predicted"):
                            raise ValueError("screen input is not successfully predicted")
                        elif node == "curate" and previous != "screened_in":
                            raise ValueError("curation needs screened-in input")
                        if previous == "failed":
                            note("failure_handling", "failed_molecule_reused", f"{cid} failed earlier", event)
                        if node in ("predict", "ml_predict"):
                            if node == "ml_predict" and ((model is None) != (state == "unscored")):
                                raise ValueError("ML/unscored state disagrees with available model")
                            key = (node, item["canonical"])
                            if item["canonical"] and key in work:
                                note("repeated_work", "possible_repeated_work", "Same molecular work repeated; recipe/cache evidence absent", event, "not_assessable")
                            work.add(key)
                            if state != "failed" and state != "unscored":
                                item["value"] = value
                                item["xtb" if node == "predict" else "ml"] = value
                        elif node == "screen":
                            margin = config.get("screening", {}).get("margin", 0)
                            accepted = inside(item["value"], margin) if _number(margin) and margin >= 0 else None
                            if accepted is None:
                                note("tool_correctness", "unavailable_screen_threshold", "Target/value/margin unavailable", event, "not_assessable")
                            elif accepted != (state == "screened_in"):
                                raise ValueError("screen status disagrees with target plus margin")
                        elif node == "curate":
                            accepted = inside(item["value"])
                            if accepted is False:
                                raise ValueError("curated molecule is outside target")
                            if accepted is None:
                                note("tool_correctness", "unavailable_curation_target", "Cannot assess curated target", event, "not_assessable")
                        item["state"] = state
                        unknown_states.discard(cid)
                if node == "curate" and (rows or "dataset_size" in outputs):
                    new_size = outputs.get("dataset_size")
                    if type(new_size) is not int or new_size < 0 or (not unknown_size and not size <= new_size <= size + len(rows)):
                        raise ValueError("invalid cumulative dataset_size")
                    size = new_size
                    unknown_size = False
            elif node == "train":
                model = TrainResult.model_validate(outputs.get("model"))
                count = sum(m["xtb"] is not None for m in registry.values())
                if any(not _number(v) for v in model.metrics.values()) or (not incomplete_effects and not unknown_states and model.n_examples != count):
                    raise ValueError("trained model counts/metrics disagree with recorded labels")
                if unknown_states or incomplete_effects:
                    note("tool_correctness", "unavailable_training_count", "Training label count cannot be reconstructed", event, "not_assessable")
            elif node == "close_round":
                stats = outputs.get("round_stats")
                names = {"generated", "duplicates", "xtb_runs", "ml_predicted", "unscored", "failed", "screened_in", "selected", "qm_calls", "hits"}
                if not isinstance(stats, dict) or not names <= stats.keys() or any(type(stats[k]) is not int or stats[k] < 0 for k in names):
                    raise ValueError("round_stats needs nonnegative integer counts")
                pool = [m for m in registry.values() if m["round"] == rnd]
                expected = dict(generated=len(pool), duplicates=sum(m["original_state"] == "duplicate" for m in pool),
                    xtb_runs=prediction_calls.get(rnd, 0),
                    ml_predicted=sum(m["ml"] is not None for m in pool), unscored=sum(m["state"] == "unscored" for m in pool),
                    failed=sum(m["state"] == "failed" for m in pool),
                    screened_in=sum(m["state"] in ("screened_in", "curated") for m in pool), hits=size - last_size)
                if not incomplete_effects and not unknown_states and not unknown_size and any(stats[k] != value for k, value in expected.items()):
                    raise ValueError("round_stats disagrees with observed changed-state evidence")
                if incomplete_effects or unknown_states or unknown_size:
                    note("tool_correctness", "incomplete_round_stats_evidence", "Some molecular states unavailable", event, "not_assessable")
                if qm is False and (stats["qm_calls"] or stats["selected"]):
                    raise ValueError("QM counters are nonzero while QM disabled")
                reported_qm_calls += stats["qm_calls"]
                last_size = size
            elif node == "continue_or_stop":
                if "stop_reason" in outputs:
                    stop_reason, stopped = outputs["stop_reason"], True
                    if stop_reason not in STOP_REASONS:
                        raise ValueError("unknown stop reason")
                elif type(outputs.get("round")) is not int or outputs["round"] != rnd + 1:
                    raise ValueError("continue needs next round number or stop_reason")
                elif rnd >= policy.get("max_rounds", rnd + 1) or (not unknown_size and size >= policy.get("target_dataset_size", size + 1)):
                    note("budget_adherence", "continued_after_budget_limit", "Continue decision exceeds reached round/dataset limit", event)
            elif node == "write_summary":
                summary_seen = True
                reason = outputs.get("stop_reason")
                if reason not in STOP_REASONS or (stop_reason is not None and reason != stop_reason):
                    raise ValueError("summary stop_reason missing or inconsistent")
                if failed_step and reason != "error":
                    note("failure_handling", "failure_stop_reason", "Failed tool requires error summary", event)
                stop_reason = reason
        except (ValueError, TypeError, KeyError) as exc:
            note("tool_correctness", "invalid_tool_call", str(exc), event)

    for rnd, observed in round_nodes.items():
        required = [n for n in declared if n != "write_summary"]
        if failed_step and rnd == failed_step[0] and failed_step[1] in required:
            required = required[:required.index(failed_step[1]) + 1]
        if set(required) - set(observed):
            note("ordering", "missing_node_evidence", f"round {rnd}: {sorted(set(required) - set(observed))}", status="not_assessable")
    if not summary_seen:
        note("failure_handling", "missing_final_summary", "Run may be incomplete", status="not_assessable")
    if not seen_rounds:
        for category in CATEGORIES:
            note(category, "missing_workflow_evidence", "No round events", status="not_assessable")
    if first_start is not None and "max_wall_time" in policy and last_end - first_start > policy["max_wall_time"]:
        note("budget_adherence", "wall_time_exceeded", "Observed trace span exceeds configured wall time")
    return report()
