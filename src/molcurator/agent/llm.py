# Client for the reasoning model, through any OpenAI-compatible chat endpoint (langchain-openai).
#
# Default: Qwen3 4B served locally by Ollama at http://localhost:11434/v1 (no API key needed).
# Hosted alternative: set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY in .env to use any
# OpenAI-compatible provider or a GPU server (vLLM, LM Studio, ...); nothing to install locally.
#
# Settings, read from the environment / .env (see .env.example), overridable per run config:
#   LLM_BASE_URL  default http://localhost:11434/v1
#   LLM_MODEL     default qwen3:4b
#   LLM_API_KEY   default "ollama" (ignored by Ollama, required by hosted providers)
#
# Startup checks (when LLM_BASE_URL is the local Ollama):
#   - Ollama server not reachable -> clear error pointing to scripts/setup.sh
#   - model not pulled yet        -> pull it automatically through Ollama's /api/pull
#
# Notes: tool calls go through bind_tools(); a CPU-only laptop (e.g. Intel Mac) needs ~40 s
# per call with Qwen3 4B, so step budgets in configs/ should account for it.
