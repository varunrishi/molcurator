# LLM-backed decisions for the agent's decision nodes (plan round, select QM batch,
# continue or stop, write summary). See .claude/specs/phase-2-agent-orchestrator/plan.md.
#
# LLMDecider implements the Decider protocol from agent/decisions.py:
#   - provider "anthropic" (default): Claude Haiku 4.5 through the Anthropic SDK, with
#     structured output (client.messages.parse(..., output_format=<decision model>)).
#   - provider "openai": any OpenAI-compatible endpoint via langchain-openai (e.g. Ollama).
#
# Per call: hard timeout (config llm.timeout_s, default 10 s) with SDK retries off; one retry
# when the answer fails validation (the error is added to the prompt); otherwise the node's
# rule from RuleDecider decides. The trace records the prompt, raw answer, retry, fallback
# reason ("invalid_answer" | "timeout" | "api_error") and duration.
#
# Settings (env / .env, overridable by the run config):
#   LLM_PROVIDER       "anthropic" (default) or "openai"
#   LLM_MODEL          default "claude-haiku-4-5"
#   ANTHROPIC_API_KEY  required for "anthropic"
#   LLM_BASE_URL, LLM_API_KEY   only for "openai"
# Safeguard: refuse to start if LLM_PROVIDER is "anthropic" and LLM_MODEL is not a
# "claude-" model (catches .env files created from the old Qwen template).
