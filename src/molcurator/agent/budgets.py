"""Budget arithmetic, enforced in code whatever the LLM decides (Phase 2, R4.1-R4.3)."""
import math
import time

from molcurator.agent.state import AgentState
from molcurator.config import BudgetSettings


def qm_calls_left(state: AgentState, budget: BudgetSettings) -> int:
    """QM calculations still allowed: max_qm_calls minus those run in finished rounds."""
    used = sum(stats["qm_calls"] for stats in state["round_stats"])
    return max(budget.max_qm_calls - used, 0)


def qm_share_this_round(state: AgentState, budget: BudgetSettings) -> int:
    """An even share of the QM calls left for this round: calls left / rounds left, rounded up, so the
    rule spreads QM over the run instead of spending it all in round 1; unused calls go to later rounds."""
    rounds_left = max(budget.max_rounds - state["round"] + 1, 1)
    return math.ceil(qm_calls_left(state, budget) / rounds_left)


def trim_qm_batch(batch: list[str], state: AgentState, budget: BudgetSettings) -> tuple[list[str], int | None]:
    """Cut the chosen QM batch to the calls left, keeping the LLM's order (R4.2).

    Returns the batch to run, and its original length if it was trimmed (else None), which the
    trace records as "trimmed_from" so it shows when the budget overrode the decision.
    """
    left = qm_calls_left(state, budget)
    return (batch[:left], len(batch)) if len(batch) > left else (batch, None)


def budget_stop_reason(state: AgentState, budget: BudgetSettings, qm_enabled: bool,
                       now: float | None = None) -> str | None:
    """Name of the first limit reached after a round, or None if another round is allowed (R4.3).

    The success case is checked first, so a run that reaches its target dataset size in the same
    round its QM budget runs out reports "target_dataset_size". max_qm_calls only applies with QM on
    (R4.1): with QM off no calls are made, so even max_qm_calls: 0 must not stop the run.
    """
    now = time.time() if now is None else now  # injectable so tests need no real waiting
    if state["dataset_size"] >= budget.target_dataset_size:
        return "target_dataset_size"
    if state["round"] >= budget.max_rounds:
        return "max_rounds"
    if qm_enabled and qm_calls_left(state, budget) == 0:
        return "max_qm_calls"
    return "max_wall_time" if now - state["started_at"] >= budget.max_wall_time else None
