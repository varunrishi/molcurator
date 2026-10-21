"""Configured chemistry stage for graph nodes; generation and persistence stay external.

The caller owns cumulative budgets, checkpoints and CURATE. This adapter preserves
the shared contracts and writes one immutable stage record per round.
"""
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from molcurator.config import RunConfig
from molcurator.schemas import Candidate, CuratedEntry, Status
from molcurator_property_validation.screening import GapCalibration, ranked_predictions
from molcurator_property_validation.tools.predict import predict
from molcurator_property_validation.tools.validate import validate


@dataclass
class ChemistryTools:
    """Inject real tools or the team's FakeTools without changing their signatures."""

    predict: Callable = predict
    validate: Callable = validate


def _check_results(inputs, results, id_field):
    expected = [getattr(item, id_field) for item in inputs]
    if [item.candidate_id for item in results] != expected:
        raise ValueError("tool violated one-result-per-input ID/order contract")
    if any(item.status is Status.ok and
           (item.value is None or not math.isfinite(item.value)) for item in results):
        raise ValueError("tool returned a nonfinite successful property")


def run_chemistry_round(
    candidates: list[Candidate], config: RunConfig, run_dir: Path, *,
    qm_calls_used: int, selected_ids: list[str] | None = None,
    exploration_slots: int = 1, tools: ChemistryTools | None = None,
    select_qm: Callable | None = None,
) -> dict:
    """Predict, prioritize/select, validate and prepare entries for one generated round.

    `select_qm(ranking, remaining)` lets an agent/LLM inspect this round's predictions
    and return ordered IDs. `selected_ids` supplies a prechosen batch instead.
    Omit both to use the deterministic ranking fallback.
    A reserved slot is charged even on QM failure, conservatively enforcing budget.
    The caller must persist/accumulate `qm_calls_charged` before the next round.
    This is a synchronous tool stage, not a resumable or wall-time-managed graph.
    """
    if config.target.name != "homo_lumo_gap" or config.target.units != "eV":
        raise ValueError("chemistry round supports homo_lumo_gap in eV only")
    calibration = GapCalibration()
    method = f"dft:{config.qm.functional}/{config.qm.basis}"
    if config.qm.backend != "orca" or method != calibration.qm_method:
        raise ValueError("calibrated stage requires ORCA B3LYP/def2-SVP")
    if not 0 <= qm_calls_used <= config.budget.max_qm_calls or exploration_slots < 0:
        raise ValueError("invalid used QM budget or exploration slot count")
    if selected_ids is not None and select_qm is not None:
        raise ValueError("choose either selected_ids or a selector callback")
    if not all(math.isfinite(x) for x in (config.screening.margin,
               *[v for v in (config.target.min, config.target.max) if v is not None])):
        raise ValueError("target bounds and screening margin must be finite")
    if not candidates:
        raise ValueError("provide a nonempty single-round candidate batch")
    ids = [c.id for c in candidates]
    rounds = {c.round for c in candidates}
    if len(ids) != len(set(ids)) or len(rounds) != 1:
        raise ValueError("candidate IDs must be unique and rounds must match")
    round_number = candidates[0].round
    if round_number > config.budget.max_rounds:
        raise ValueError("candidate round exceeds configured round budget")
    if selected_ids is not None and (
        len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(ids)
    ):
        raise ValueError("selected IDs must be unique members of this batch")
    folder = Path(run_dir).resolve() / "chemistry" / f"round-{round_number}"
    folder.mkdir(parents=True, exist_ok=False)
    record = dict(status="started", round=round_number,
                  candidates=[c.model_dump(mode="json") for c in candidates],
                  config=config.model_dump(mode="json"), qm_calls_used_before=qm_calls_used,
                  qm_calls_charged=0, predictions=[], ranking=[], qm_batch_ids=[],
                  qm_results=[], curated_entries=[], geometry_reports={})
    path = folder / "stage.json"

    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False))
        temporary.replace(path)

    save()
    tools = tools or ChemistryTools()
    try:
        predictions = tools.predict(candidates, config.target, folder / "xyz")
        _check_results(candidates, predictions, "id")
        record["predictions"] = [p.model_dump(mode="json") for p in predictions]
        ranking = ranked_predictions(predictions, config.target, calibration,
                                     margin_ev=config.screening.margin)
        record["ranking"] = ranking
        by_id = {p.candidate_id: p for p in predictions}
        eligible = [r for r in ranking if r["status"] == "ok" and
                    by_id[r["candidate_id"]].xyz_path is not None]
        valid_ids = {r["candidate_id"] for r in eligible}
        remaining = config.budget.max_qm_calls - qm_calls_used
        if select_qm is not None:
            # Persist cheap results before an external decision; no QM is reserved yet.
            save()
            selected_ids = select_qm(ranking, remaining)
        if selected_ids is not None:
            if (len(selected_ids) != len(set(selected_ids)) or
                    not set(selected_ids) <= valid_ids):
                raise ValueError("selected QM IDs require successful predictions and geometries")
            chosen = selected_ids[:remaining]
            record.update(selection="agent_supplied", trimmed_from=len(selected_ids))
        else:
            slots = min(remaining, len(eligible))
            outside = [r["candidate_id"] for r in eligible if not r["selected"]]
            # Keep at least one prioritized slot when a batch has any capacity.
            n_explore = min(exploration_slots, max(0, slots - 1), len(outside))
            exploration = random.Random(config.rng_seed + round_number).sample(outside, n_explore)
            prioritized = [r["candidate_id"] for r in eligible
                           if r["candidate_id"] not in exploration]
            chosen = prioritized[:slots - n_explore] + exploration
            record.update(selection="calibrated_rules_with_exploration",
                          exploration_ids=exploration)
        batch = [by_id[cid] for cid in chosen]
        # Persist the reservation before invoking expensive work, including failed calls.
        record.update(qm_batch_ids=chosen, qm_calls_charged=len(batch))
        save()
        results = tools.validate(batch, config.target, config.qm) if batch else []
        _check_results(batch, results, "candidate_id")
        record["qm_results"] = [r.model_dump(mode="json") for r in results]
        candidates_by_id = {c.id: c for c in candidates}
        entries = []
        for result in results:
            if result.method != method:
                raise ValueError("QM result method differs from configured reference method")
            if result.status is not Status.ok:
                continue
            target = config.target
            if (target.min is not None and result.value < target.min or
                    target.max is not None and result.value > target.max):
                continue
            candidate = candidates_by_id[result.candidate_id]
            prediction = by_id[result.candidate_id]
            entries.append(CuratedEntry(
                id=candidate.id, smiles=candidate.smiles, xyz_path=prediction.xyz_path,
                properties={"xtb": prediction.value, result.method: result.value},
                provenance=dict(parent=candidate.parent_smiles, generator=candidate.generator,
                                round=str(candidate.round), seeds=json.dumps(config.seeds),
                                stage_path=str(path)),
            ))
        record["curated_entries"] = [e.model_dump(mode="json") for e in entries]
        # Surface FF weights directly for the agent's summary; don't invent data for fakes.
        for prediction in predictions:
            if prediction.xyz_path is None:
                continue
            report = prediction.xyz_path.parent / "calculations" / prediction.candidate_id / "xtb" / "geometry_report.json"
            if report.is_file():
                record["geometry_reports"][prediction.candidate_id] = json.loads(report.read_text())
        record.update(status="ok", target_hits=len(entries))
        save()
        return dict(predictions=predictions, ranking=ranking, qm_results=results,
                    curated_entries=entries, qm_calls_charged=len(batch),
                    qm_batch_ids=chosen, stage_path=path,
                    geometry_reports=record["geometry_reports"])
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save()
        raise
