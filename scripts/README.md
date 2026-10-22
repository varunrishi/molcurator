# Scripts

- `setup.sh`: one-command setup (uv + Python dependencies, xtb, Ollama + `qwen3:4b`, `.env`). Safe to re-run; `--no-llm` skips the Ollama step.
- `check_llm_decider.py <out_dir>`: live check of `decisions: llm`, a 3-round run with real Claude Haiku 4.5 and fake chemistry. It prints each decision and the summary next to the recorded round stats. It calls the Anthropic API (about 7 requests, a few cents) and needs `ANTHROPIC_API_KEY` in `.env`.

Other one-off helpers go here, e.g. downloading the Mol2Mol prior.
