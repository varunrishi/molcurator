"""Tool-step nodes: each calls one tool through the Toolset and updates the molecule records (R1).

Every node is (state, config, tools) -> dict of changed fields; graph.py binds config and tools.
"""
import random
from pathlib import Path

from molcurator.agent.decisions import RoundPlan
from molcurator.agent.state import AgentState, MoleculeRecord, RoundStats
from molcurator.agent.summaries import best_estimate, parent_options, target_distance
from molcurator.agent.toolset import Toolset
from molcurator.config import RunConfig
from molcurator.schemas import Candidate, CuratedEntry, Prediction, Status, TrainingExample, TrainResult


def generate_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """GENERATE: candidates from this round's chosen parents; repeats are kept as "duplicate" (R1.3, R1.5)."""
    plan = RoundPlan(**state["round_plan"])
    options = parent_options(state, config)  # the same table the plan-round decision chose from
    parents = [options[pid] for pid in plan.parents]  # an unknown id raises: a whole-step error (R1.7)
    seen = {m["smiles"] for m in state["molecules"].values()} | set(config.seeds)
    molecules = dict(state["molecules"])
    for c in tools.generate(parents, plan.settings(), state["round"], config.rng_seed):
        molecules[c.id] = MoleculeRecord(id=c.id, smiles=c.smiles, round=c.round, parent=c.parent_smiles,
                                         status="duplicate" if c.smiles in seen else "generated",
                                         xtb=None, ml=None, qm=None, qm_method=None, xyz_path=None, error=None)
        seen.add(c.smiles)
    return {"molecules": molecules}


def predict_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """PREDICT: xTB value for each newly generated molecule; failures are recorded, not dropped (R1.6)."""
    molecules = dict(state["molecules"])
    generator = state["round_plan"]["generator"]  # records don't store it; the round's plan does
    todo = [Candidate(id=m["id"], smiles=m["smiles"], parent_smiles=m["parent"], round=m["round"], generator=generator)
            for m in molecules.values() if m["status"] == "generated"]  # duplicates are skipped (R1.5)
    # xTB is slow, so only a seeded random sample of this round's new candidates gets it (R10.1);
    # the rest stay "generated" for ML PREDICT. Sorting by id keeps the call order stable.
    rng = random.Random(f"xtb-sample-{config.rng_seed}-{state['round']}")
    todo = sorted(rng.sample(todo, min(config.predict.n_xtb, len(todo))), key=lambda c: c.id)
    results = tools.predict(todo, config.target, Path(state["run_dir"]) / "xyz")
    if sorted(p.candidate_id for p in results) != sorted(c.id for c in todo):
        raise ValueError("predict must return exactly one result per candidate (R2.4)")
    for p in results:
        ok = p.status is Status.ok
        molecules[p.candidate_id] = {**molecules[p.candidate_id], "status": "predicted" if ok else "failed",
                                     "xtb": p.value, "error": p.error,
                                     "xyz_path": str(p.xyz_path) if p.xyz_path else None}
    return {"molecules": molecules}


def train_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """TRAIN: once enough molecules have xTB values, fit the ML model on all of them (R10.2, R10.3).

    Below train.min_examples it changes nothing, so ML PREDICT leaves candidates unscored (R10.5).
    """
    examples = [TrainingExample(smiles=m["smiles"], value=m["xtb"])
                for m in state["molecules"].values() if m["xtb"] is not None]
    if len(examples) < config.train.min_examples:
        return {}
    result = tools.train(examples, config.target, Path(state["run_dir"]) / "models" / f"round-{state['round']}")
    return {"model": result.model_dump(mode="json")}  # plain data, so checkpoints stay simple


def ml_predict_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """ML PREDICT: score this round's candidates that xTB did not run on (R10.4).

    Without a trained model yet they become "unscored", a final status (R10.5).
    """
    molecules = dict(state["molecules"])
    ids = [i for i, m in molecules.items() if m["status"] == "generated"]  # outside the xTB sample
    if not ids:
        return {}
    if state["model"] is None:
        return {"molecules": {**molecules, **{i: {**molecules[i], "status": "unscored"} for i in ids}}}
    generator = state["round_plan"]["generator"]
    todo = [Candidate(id=i, smiles=molecules[i]["smiles"], parent_smiles=molecules[i]["parent"],
                      round=molecules[i]["round"], generator=generator) for i in ids]
    results = tools.ml_predict(todo, config.target, TrainResult(**state["model"]))
    if sorted(p.candidate_id for p in results) != sorted(ids):
        raise ValueError("ml_predict must return exactly one result per candidate (R2.4)")
    for p in results:
        ok = p.status is Status.ok
        molecules[p.candidate_id] = {**molecules[p.candidate_id], "status": "ml_predicted" if ok else "failed",
                                     "ml": p.value, "error": p.error}
    return {"molecules": molecules}


def screen_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """SCREEN (a rule, not an LLM call): a molecule passes if its xTB value lies in the target
    window widened by the screening margin (R1.4). Only this round's predicted molecules change."""
    molecules = dict(state["molecules"])
    for mol_id, m in molecules.items():
        if m["status"] in ("predicted", "ml_predicted"):  # xTB-sampled and ML-scored molecules (R1.4)
            # 1e-9: floating-point slack, so a value exactly on the widened boundary still passes
            inside = target_distance(best_estimate(m), config.target) <= config.screening.margin + 1e-9
            molecules[mol_id] = {**m, "status": "screened_in" if inside else "screened_out"}
    return {"molecules": molecules}


def validate_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """VALIDATE: QM value for each molecule in this round's QM batch, which is already trimmed to the
    QM budget (R4.2) and possibly edited at approval (R5.2). An empty batch runs no QM."""
    if not state["qm_batch"]:
        return {}
    molecules = dict(state["molecules"])
    items = [Prediction(candidate_id=i, status=Status.ok, value=molecules[i]["xtb"], xyz_path=molecules[i]["xyz_path"])
             for i in state["qm_batch"]]  # QM starts from each molecule's xTB geometry
    results = tools.validate(items, config.target, config.qm)
    if sorted(q.candidate_id for q in results) != sorted(state["qm_batch"]):
        raise ValueError("validate must return exactly one result per molecule (R2.4)")
    for q in results:
        ok = q.status is Status.ok
        molecules[q.candidate_id] = {**molecules[q.candidate_id], "status": "validated" if ok else "failed",
                                     "qm": q.value, "qm_method": q.method, "error": q.error}
    return {"molecules": molecules}


def curate_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """CURATE: molecules whose best estimate (QM, else xTB, else ML) lies inside the target, with no
    screening margin, join the dataset with a value at every level they have (R11.2, R11.3).
    With QM on, only this round's QM-validated molecules qualify; with QM off, screened-in ones do."""
    molecules = dict(state["molecules"])
    pool = ([molecules[i] for i in state["qm_batch"] if molecules[i]["status"] == "validated"] if config.qm.enabled
            else [m for m in molecules.values() if m["status"] == "screened_in"])
    hits = [m for m in pool if target_distance(best_estimate(m), config.target) <= 1e-9]
    if not hits:
        return {}
    levels = lambda m: {"ml": m["ml"], "xtb": m["xtb"], m["qm_method"]: m["qm"]}  # noqa: E731
    entries = [CuratedEntry(id=m["id"], smiles=m["smiles"], xyz_path=m["xyz_path"], validated=m["qm"] is not None,
                            properties={k: v for k, v in levels(m).items() if k and v is not None},
                            provenance={"parent": m["parent"], "round": str(m["round"]), "seeds": ";".join(config.seeds)})
               for m in hits]
    size = tools.curate(entries, Path(state["run_dir"]))  # idempotent, so a resumed re-run adds nothing (R7.2)
    for m in hits:
        molecules[m["id"]] = {**m, "status": "curated"}
    return {"molecules": molecules, "dataset_size": size}


def close_round_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """End of round: count what happened and append a RoundStats entry (R3.3, R4.1, R8.3)."""
    r, molecules, batch = state["round"], state["molecules"], state["qm_batch"]
    this_round = [m for m in molecules.values() if m["round"] == r]
    batch_records = [molecules[i] for i in batch]
    failed = {m["id"] for m in this_round + batch_records if m["status"] == "failed"}
    passed = {"screened_in", "selected", "validated", "curated"}
    # A QM failure has an xTB value (it passed the screen first); an xTB failure has none.
    screened_in = [m for m in this_round if m["status"] in passed or (m["status"] == "failed" and m["xtb"] is not None)]
    new = [m for m in this_round if m["status"] != "duplicate"]
    stats = RoundStats(round=r, generated=len(this_round),
                       duplicates=len(this_round) - len(new),
                       xtb_runs=min(config.predict.n_xtb, len(new)),  # same size PREDICT sampled (R10.1)
                       ml_predicted=sum(m["ml"] is not None for m in this_round),
                       unscored=sum(m["status"] == "unscored" for m in this_round),
                       failed=len(failed), screened_in=len(screened_in),
                       selected=len(batch), qm_calls=len(batch),
                       # dataset growth this round: right with QM on or off, and on resume (curate is idempotent)
                       hits=state["dataset_size"] - sum(s["hits"] for s in state["round_stats"]))
    return {"round_stats": [*state["round_stats"], stats]}
