"""Compact views of the state, shared by the rules and the LLM prompts so both choose from
exactly the same options (Phase 2, R3.2, R3.6)."""
from molcurator.agent.state import AgentState, MoleculeRecord
from molcurator.config import RunConfig
from molcurator.schemas import PropertyTarget


def target_distance(value: float, target: PropertyTarget) -> float:
    """0 inside the target window, otherwise how far outside it (works for one-sided targets)."""
    below = target.min - value if target.min is not None else 0.0
    above = value - target.max if target.max is not None else 0.0
    return max(below, above, 0.0)


def best_estimate(m: MoleculeRecord) -> float | None:
    """The most accurate value a molecule has: QM, else xTB, else ML (R1.4, R11.2)."""
    for level in ("qm", "xtb", "ml"):
        if m[level] is not None:
            return m[level]
    return None


def parent_options(state: AgentState, config: RunConfig) -> dict[str, str]:
    """Molecules the plan-round decision may mutate, id -> SMILES: seeds, curated, then best xTB."""
    options = {f"seed-{i}": smiles for i, smiles in enumerate(config.seeds)}
    scored = [m for m in state["molecules"].values() if best_estimate(m) is not None]
    scored.sort(key=lambda m: (m["status"] != "curated", target_distance(best_estimate(m), config.target)))
    for m in scored[: max(config.llm.max_table_rows - len(options), 0)]:
        options[m["id"]] = m["smiles"]
    return options


def screened_candidates(state: AgentState, config: RunConfig) -> list[MoleculeRecord]:
    """The QM-batch table: screened-in molecules not yet sent to QM, closest to the target first (R3.2).

    Ties are broken by id, so seeded runs and resumes see exactly the same order.
    """
    pool = [m for m in state["molecules"].values() if m["status"] == "screened_in"]
    pool.sort(key=lambda m: (target_distance(best_estimate(m), config.target), m["id"]))
    return pool[: config.llm.max_table_rows]
