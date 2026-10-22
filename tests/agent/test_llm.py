"""LLMDecider with a fake Claude: valid answers, one retry, then the rule (Phase 2, R3.5, R9.2, R9.5)."""
import anthropic
import httpx
import pytest

from molcurator.agent.decisions import RoundPlan
from molcurator.agent.graph import initial_state
from molcurator.agent.llm import LLMDecider
from molcurator.config import load_config
from tests.agent.fakes import FakeClaude
from tests.agent.test_graph import CONFIG

STOP, INVALID = '{"decision": "stop", "reason": "hits dried up"}', '{"decision": "maybe", "reason": "unsure"}'
REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize("replies, source, fallback, retried", [
    ([STOP], "llm", None, False),
    ([INVALID, STOP], "llm", None, True),
    ([INVALID, INVALID], "rule", "invalid_answer", True),
    ([anthropic.APITimeoutError(REQUEST)], "rule", "timeout", False),
    ([anthropic.APIConnectionError(request=REQUEST)], "rule", "api_error", False)])
def test_decision_retries_once_then_falls_back_to_the_rule(replies, source, fallback, retried):
    """R3.5, R9.5: a valid answer is used; an invalid one is retried once with the error; then the rule decides."""
    claude = FakeClaude(*replies)
    decided = LLMDecider(claude, "claude-haiku-4-5", 10).continue_or_stop(initial_state("t", "unused"), load_config(CONFIG))
    assert (decided.source, decided.fallback, decided.retried) == (source, fallback, retried)
    assert decided.decision.decision == ("stop" if source == "llm" else "continue")  # the rule: budget remains
    assert len(claude.prompts) == len(replies) and (not retried or "rejected" in claude.prompts[1])


def test_plan_outside_the_limits_is_rejected_with_the_reason_and_retried():
    """R3.1, R3.5: an unknown parent or an out-of-range setting is rejected; the retry prompt says why."""
    def plan(parents, n):
        return RoundPlan(parents=parents, generator="stoned_selfies", n_candidates=n, mutation_strength=1,
                         reason="smaller steps").model_dump_json()
    claude = FakeClaude(plan(["seed-0", "r9-c999"], 5000), plan(["seed-0"], 300))
    decided = LLMDecider(claude, "claude-haiku-4-5", 10).plan_round(initial_state("t", "unused"), load_config(CONFIG))
    assert "seed-0 |" in claude.prompts[0] and "n_candidates 1-1000" in claude.prompts[0]  # table and ranges shown
    assert "unknown parent id 'r9-c999'" in claude.prompts[1] and "between 1 and 1000" in claude.prompts[1]
    assert (decided.source, decided.retried, decided.decision.n_candidates) == ("llm", True, 300)
