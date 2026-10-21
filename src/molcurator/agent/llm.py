"""LLM-backed decisions: Claude through the Anthropic SDK, with the rules as fallback (Phase 2, R3, R9)."""
import os
import time
from collections.abc import Callable
from dataclasses import replace

import anthropic
from dotenv import load_dotenv

from molcurator.agent.decisions import (ContinueDecision, Decided, QMBatchDecision, RoundPlan, RuleDecider,
                                        RunSummary, check_plan)
from molcurator.agent.prompts import SYSTEM, continue_prompt, plan_round_prompt, summary_prompt
from molcurator.agent.state import AgentState
from molcurator.config import RunConfig


class LLMDecider:
    """Asks Claude for each decision; an invalid answer is retried once, then the rule decides (R3.5)."""

    def __init__(self, client: anthropic.Anthropic, model: str, timeout_s: float):
        self.client, self.model, self.timeout_s = client, model, timeout_s  # client built with max_retries=0
        self.rules = RuleDecider()  # every fallback is exactly what rules mode would decide (R3.5)

    def plan_round(self, state: AgentState, config: RunConfig) -> Decided[RoundPlan]:
        return self._ask(RoundPlan, plan_round_prompt(state, config), lambda plan: check_plan(plan, state, config),
                         lambda: self.rules.plan_round(state, config))

    def select_qm_batch(self, state: AgentState, config: RunConfig) -> Decided[QMBatchDecision]:
        return self.rules.select_qm_batch(state, config)  # QM is not wired into the v1 graph yet; prompt comes with it

    def continue_or_stop(self, state: AgentState, config: RunConfig) -> Decided[ContinueDecision]:
        return self._ask(ContinueDecision, continue_prompt(state, config), lambda d: None,  # budgets: enforced in code
                         lambda: self.rules.continue_or_stop(state, config))

    def write_summary(self, state: AgentState, config: RunConfig) -> Decided[RunSummary]:
        return self._ask(RunSummary, summary_prompt(state, config), lambda d: None,
                         lambda: self.rules.write_summary(state, config))

    def _ask(self, model_cls, prompt: str, check: Callable, rule: Callable[[], Decided]) -> Decided:
        """One validated decision from Claude, or the rule's, with what happened recorded (R3.5, R6.2, R9.5)."""
        start, sent, raw, error, fallback = time.perf_counter(), prompt, None, None, "invalid_answer"
        for attempt in range(2):  # the first answer, then one retry with the error added (R3.5)
            sent = prompt if error is None else f"{prompt}\n\nYour previous answer was rejected: {error}\nAnswer again."
            try:
                reply = self.client.messages.parse(model=self.model, max_tokens=1024, system=SYSTEM, output_format=model_cls,
                                                   messages=[{"role": "user", "content": sent}], timeout=self.timeout_s)
                raw = "".join(b.text for b in reply.content if b.type == "text")
                if reply.parsed_output is None:
                    raise ValueError("no structured answer")
                check(reply.parsed_output)  # e.g. check_plan: config ranges and offered ids (R3.1)
                return Decided(reply.parsed_output, "llm", None, attempt == 1, sent, raw, time.perf_counter() - start)
            except ValueError as e:  # bad JSON, schema mismatch, or a check failure: worth one retry
                error = str(e)
            except anthropic.APITimeoutError:  # checked before APIError, which it subclasses
                fallback = "timeout"
                break
            except anthropic.APIError:
                fallback = "api_error"
                break
        return replace(rule(), fallback=fallback, retried=error is not None and attempt == 1, prompt=sent,
                       raw_response=raw, duration_s=time.perf_counter() - start)


def make_llm_decider(config: RunConfig) -> LLMDecider:
    """The decider for decisions: llm. Provider and model come from the config, else LLM_PROVIDER /
    LLM_MODEL in the environment or .env (R9.1); problems are reported before the run starts."""
    load_dotenv()  # fills in from .env; variables already set in the shell win
    provider = config.llm.provider or os.environ.get("LLM_PROVIDER", "anthropic")
    model = config.llm.model or os.environ.get("LLM_MODEL", "claude-haiku-4-5")
    if provider != "anthropic":
        raise NotImplementedError(f"LLM provider {provider!r} is not built yet; use anthropic, or decisions: rules")
    if not model.startswith("claude-"):  # e.g. an old .env with LLM_MODEL=qwen3:4b
        raise ValueError(f"LLM_MODEL={model!r} is not a Claude model; set e.g. LLM_MODEL=claude-haiku-4-5 in .env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is not set; add it to .env, or use decisions: rules")
    return LLMDecider(anthropic.Anthropic(max_retries=0), model, config.llm.timeout_s)  # SDK retries off (R9.5)
