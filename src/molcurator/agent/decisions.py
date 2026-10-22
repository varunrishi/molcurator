"""Decision models for the agent's four decision nodes, and the deciders that produce them (R3).

Each model is the structured answer a decision node expects, from the LLM or from a rule.
Fields are flat and simple so a fast model fills them in reliably.
"""
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from molcurator.agent.budgets import budget_stop_reason, qm_share_this_round
from molcurator.agent.state import AgentState
from molcurator.agent.summaries import parent_options, screened_candidates
from molcurator.config import RunConfig
from molcurator.schemas import GenerationSettings


class RoundPlan(BaseModel):
    """Plan-round decision: which molecules to mutate this round, and how (R3.1)."""

    parents: list[str] = Field(min_length=1, max_length=10)  # ids from the parent table shown, e.g. "seed-0"
    generator: str
    n_candidates: int
    mutation_strength: int
    reason: str = Field(min_length=1)  # one sentence; shown in progress and the trace

    def settings(self) -> GenerationSettings:
        """The generate() settings; GenerationSettings enforces the hard bounds."""
        return GenerationSettings(generator=self.generator, n_candidates=self.n_candidates,
                                  mutation_strength=self.mutation_strength)


def check_plan(plan: RoundPlan, state: AgentState, config: RunConfig) -> None:
    """Raise ValueError if a round plan breaks the config's limits or names a parent it was not offered
    (R3.1). The message lists every problem: it is sent back to the LLM on its one retry (R3.5)."""
    limits, offered = config.generation, parent_options(state, config)
    problems = [f"unknown parent id {p!r}; choose from {sorted(offered)}" for p in plan.parents if p not in offered]
    if len(set(plan.parents)) != len(plan.parents):
        problems.append("parent ids must not repeat")
    if plan.generator not in limits.generators:
        problems.append(f"generator must be one of {limits.generators}")
    if not 1 <= plan.n_candidates <= limits.max_candidates:
        problems.append(f"n_candidates must be between 1 and {limits.max_candidates}")
    if not 1 <= plan.mutation_strength <= limits.max_mutation_strength:
        problems.append(f"mutation_strength must be between 1 and {limits.max_mutation_strength}")
    if problems:
        raise ValueError("; ".join(problems))


class QMBatchDecision(BaseModel):
    """Select-QM-batch decision: which screened candidates get expensive QM, best first (R3.2)."""

    select: list[str]  # ids from the candidate table shown; may be empty; order matters for trimming (R4.2)
    reason: str = Field(min_length=1)


class ContinueDecision(BaseModel):
    """Continue-or-stop decision after a round; budgets can still overrule "continue" (R3.3, R4.3)."""

    decision: Literal["continue", "stop"]  # not a bool: "continue" is a Python keyword, and a word is unambiguous
    reason: str = Field(min_length=1)


class RunSummary(BaseModel):
    """Write-summary decision: a short Markdown report of the run, saved as summary.md (R3.4)."""

    summary: str = Field(min_length=1)


T = TypeVar("T", RoundPlan, QMBatchDecision, ContinueDecision, RunSummary)


@dataclass
class Decided(Generic[T]):
    """A decision plus how it was made; decision nodes pass the rest to the trace (R6.2)."""

    decision: T
    source: Literal["llm", "rule"]
    fallback: str | None = None  # why a rule decided: "rules_mode" | "invalid_answer" | "timeout" | "api_error"
    retried: bool = False  # the LLM's first answer failed validation and it was asked again
    prompt: str | None = None
    raw_response: str | None = None
    duration_s: float = 0.0


class Decider(Protocol):
    """Makes the four decisions. Implementations: RuleDecider (here), LLMDecider (llm.py),
    ScriptedDecider (tests). The graph only depends on this interface (R9.1, R9.4)."""

    def plan_round(self, state: AgentState, config: RunConfig) -> Decided[RoundPlan]: ...

    def select_qm_batch(self, state: AgentState, config: RunConfig) -> Decided[QMBatchDecision]: ...

    def continue_or_stop(self, state: AgentState, config: RunConfig) -> Decided[ContinueDecision]: ...

    def write_summary(self, state: AgentState, config: RunConfig) -> Decided[RunSummary]: ...


class RuleDecider:
    """The fallback rules (R3.5): every decision in "rules" mode, and LLMDecider's fallback when an
    answer is invalid or times out. Deterministic and instant."""

    def plan_round(self, state: AgentState, config: RunConfig) -> Decided[RoundPlan]:
        # Repeat the previous round's settings (round 1: config defaults), mutating the top 3 parents.
        prev = state["round_plan"]
        settings = RoundPlan(**prev).settings() if prev else config.generation.defaults
        plan = RoundPlan(parents=list(parent_options(state, config))[:3], **settings.model_dump(),
                         reason="Rule: repeat the previous settings with the best parents so far.")
        return Decided(plan, source="rule", fallback="rules_mode")

    def select_qm_batch(self, state: AgentState, config: RunConfig) -> Decided[QMBatchDecision]:
        # Closest to the target first, up to this round's even share of the QM calls left.
        ids = [m["id"] for m in screened_candidates(state, config)[: qm_share_this_round(state, config.budget)]]
        batch = QMBatchDecision(select=ids, reason=f"Rule: the {len(ids)} screened candidates closest to the target "
                                                   "(an even share of the QM calls left per round).")
        return Decided(batch, source="rule", fallback="rules_mode")

    def continue_or_stop(self, state: AgentState, config: RunConfig) -> Decided[ContinueDecision]:
        # Continue while any budget remains; the graph enforces budgets either way (R4.3).
        limit = budget_stop_reason(state, config.budget, config.qm.enabled)
        choice = ContinueDecision(decision="stop" if limit else "continue",
                                  reason=f"Rule: stop, {limit} reached." if limit else "Rule: budget remains.")
        return Decided(choice, source="rule", fallback="rules_mode")

    def write_summary(self, state: AgentState, config: RunConfig) -> Decided[RunSummary]:
        # A fixed template from the run statistics, so every run gets a summary, even after an error.
        stats, t = state["round_stats"], config.target
        total = lambda key: sum(s[key] for s in stats)  # noqa: E731 (local shorthand)
        text = (f"# Run {state['run_id']}\n\nTarget: {t.name} (min {'-' if t.min is None else t.min}, "
                f"max {'-' if t.max is None else t.max} {t.units}).\n\n"
                f"Rounds: {len(stats)}. Generated: {total('generated')}. QM calculations: {total('qm_calls')}. "
                f"Confirmed hits: {total('hits')} (dataset size {state['dataset_size']}).\n\n"
                f"Stopped because: {state['stop_reason']}.")
        return Decided(RunSummary(summary=text), source="rule", fallback="rules_mode")
