"""Tool-step nodes: each calls one tool through the Toolset and updates the molecule records (R1).

Every node is (state, config, tools) -> dict of changed fields; graph.py binds config and tools.
"""
from pathlib import Path

from molcurator.agent.decisions import RoundPlan
from molcurator.agent.state import AgentState, MoleculeRecord, RoundStats
from molcurator.agent.summaries import parent_options, target_distance
from molcurator.agent.toolset import Toolset
from molcurator.config import RunConfig
from molcurator.schemas import Candidate, CuratedEntry, Prediction, Status


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
                                         xtb=None, qm=None, qm_method=None, xyz_path=None, error=None)
        seen.add(c.smiles)
    return {"molecules": molecules}


def predict_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """PREDICT: xTB value for each newly generated molecule; failures are recorded, not dropped (R1.6)."""
    molecules = dict(state["molecules"])
    generator = state["round_plan"]["generator"]  # records don't store it; the round's plan does
    todo = [Candidate(id=m["id"], smiles=m["smiles"], parent_smiles=m["parent"], round=m["round"], generator=generator)
            for m in molecules.values() if m["status"] == "generated"]  # duplicates are skipped (R1.5)
    results = tools.predict(todo, config.target, Path(state["run_dir"]) / "xyz")
    if sorted(p.candidate_id for p in results) != sorted(c.id for c in todo):
        raise ValueError("predict must return exactly one result per candidate (R2.4)")
    for p in results:
        ok = p.status is Status.ok
        molecules[p.candidate_id] = {**molecules[p.candidate_id], "status": "predicted" if ok else "failed",
                                     "xtb": p.value, "error": p.error,
                                     "xyz_path": str(p.xyz_path) if p.xyz_path else None}
    return {"molecules": molecules}


def screen_node(state: AgentState, config: RunConfig, tools: Toolset) -> dict:
    """SCREEN (a rule, not an LLM call): a molecule passes if its xTB value lies in the target
    window widened by the screening margin (R1.4). Only this round's predicted molecules change."""
    molecules = dict(state["molecules"])
    for mol_id, m in molecules.items():
        if m["status"] == "predicted":
            # 1e-9: floating-point slack, so a value exactly on the widened boundary still passes
            inside = target_distance(m["xtb"], config.target) <= config.screening.margin + 1e-9
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
    """CURATE: molecules whose QM value lies inside the target (no screening margin) join the benchmark
    set, with properties from both levels of theory; near misses stay "validated"."""
    molecules = dict(state["molecules"])
    hits = [molecules[i] for i in state["qm_batch"] if molecules[i]["status"] == "validated"
            and target_distance(molecules[i]["qm"], config.target) <= 1e-9]
    if not hits:
        return {}
    entries = [CuratedEntry(id=m["id"], smiles=m["smiles"], xyz_path=m["xyz_path"],
                            properties={"xtb": m["xtb"], m["qm_method"]: m["qm"]},
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
    stats = RoundStats(round=r, generated=len(this_round),
                       duplicates=sum(m["status"] == "duplicate" for m in this_round),
                       failed=len(failed), screened_in=len(screened_in),
                       selected=len(batch), qm_calls=len(batch),
                       hits=sum(m["status"] == "curated" for m in batch_records))
    return {"round_stats": [*state["round_stats"], stats]}
