# Tech Stack

## Agent layer

| Component | Choice | Role |
|-----------|--------|------|
| Orchestrator | [LangGraph](https://github.com/langchain-ai/langgraph) | Stateful agent graph; routes between tools and holds the loop state |
| Decision model | Claude Haiku 4.5 (`claude-haiku-4-5`) through the Anthropic Python SDK (`anthropic`), with structured output (`output_config.format` JSON schema). Optional: any OpenAI-compatible endpoint (`langchain-openai`), e.g. local Ollama | Makes the decisions at the workflow's decision nodes (plan round, pick QM batch, continue or stop, summary) |
| Rule-based decisions | Plain Python fallback rules, one per decision node | Used when an LLM answer is invalid or times out, and as a whole-run mode (`decisions: rules`) for tests and fast runs |

## Tools

| Tool | Libraries | Notes |
|------|-----------|-------|
| GENERATE | [RDKit](https://www.rdkit.org/), Mol2Mol via [REINVENT4](https://github.com/MolecularAI/REINVENT4), or [STONED SELFIES](https://github.com/the-matter-lab/stoned-selfies) | Seed-based generation of candidate SMILES; RDKit for sanitisation and deduplication |
| PREDICT | RDKit (3D embedding), xTB | SMILES → 3D geometry → xTB optimisation → property extraction (e.g. HOMO-LUMO gap) |
| TRAIN | [ChemProp](https://github.com/chemprop/chemprop) | Property model trained on the growing dataset; uncertainty estimates (e.g. ensembles) drive the selection for validation |
| VALIDATE | [PySCF](https://pyscf.org/) or [ORCA](https://www.faccts.de/orca/) | Higher-accuracy QM (DFT / TD-DFT for S1 and T1 energies) |
| CURATE | pandas + Pydantic models, CSV + XYZ files per run | Stores SMILES, structure and properties for each level of theory |
| EVALUATE | Custom pipeline over LangGraph traces | Scores agent trajectories and tool-call correctness |

## Language and environment

- Python 3.11+ (ChemProp v2 requires 3.11)
- Setup: `scripts/setup.sh` does everything in one command (uv + `uv sync`, xtb, Ollama + model, `.env`); safe to re-run
- Packaging: `pyproject.toml` (setuptools build, `src/` layout), installable with `uv sync` (locked by `uv.lock`) or `pip install -e .`
- Dev tools (uv dependency group `dev`): pytest, ruff, jupyter
- Python dependencies: langgraph, langchain-core, anthropic, langchain-openai (optional backend), rdkit, selfies, pyscf, chemprop (brings torch + lightning), pandas, pydantic, pyyaml, typer, python-dotenv
- Intel-Mac limits, set with platform markers in `pyproject.toml`: torch 2.2.2 (the last Intel-Mac wheel), so `numpy<2` and `rdkit<2026`. Other platforms get current versions.
- External binaries (not on PyPI):
  - **xtb**: found or installed by `setup.sh`: existing `XTB_BIN` / `PATH`, else a conda-forge env named `xtb`, else the Linux release in `.tools/` (Homebrew also works by hand); the path is saved as `XTB_BIN` in `.env`
  - **Ollama** (optional): serves a local model such as `qwen3:4b` for the OpenAI-compatible backend; not needed for the default Claude backend
- Settings: `.env` (gitignored, created from `.env.example`): `XTB_BIN`, `ANTHROPIC_API_KEY`, `LLM_PROVIDER` (`anthropic` default, or `openai`), `LLM_MODEL` (default `claude-haiku-4-5`), and for the OpenAI-compatible backend only `LLM_BASE_URL` / `LLM_API_KEY`; variables already in the environment take precedence
  - **ORCA** (optional): needs a licence
  - **REINVENT4** (optional): Mol2Mol generator, installed from its git repo

## Project structure

```
molcurator/
├── pyproject.toml / uv.lock / .python-version / .env.example
├── src/molcurator/
│   ├── tools/            generate.py, predict.py, train.py, validate.py, curate.py, evaluate.py
│   ├── agent/            graph.py (LangGraph), state.py, llm.py (Anthropic client; optional OpenAI-compatible backend), prompts.py
│   ├── chem/             convert.py (SMILES/SELFIES/RDKit), geometry.py (3D embedding, XYZ I/O)
│   ├── schemas.py        Pydantic models shared by all tools
│   └── cli.py            Typer CLI, installed as `molcurator`
├── configs/              homo_lumo.yaml, tadf.yaml (one per use case)
├── data/seeds/           seed molecules (committed)
├── data/runs/<run_id>/   dataset, xyz/, models/, traces/ (gitignored)
├── tests/                one test file per tool
├── scripts/setup.sh      one-command setup
├── notebooks/  demo/
```

Design rules:
- Each tool is a plain typed function that runs without the LLM; `agent/graph.py` only wraps tools for LangGraph.
- `schemas.py` is the data contract between steps.
- Use cases differ only by config file, not by code.
- All outputs of a run go in its own `data/runs/<run_id>/` folder; EVALUATE reads traces from there.

## Decision model: measured latency (2026-10-20)

One QM-batch decision (5-row table, JSON-schema answer), 3 calls per model, on the dev laptop:

| Model | Median | Valid answers | Notes |
|---|---|---|---|
| Claude Haiku 4.5 | 2.18 s | 3/3 | chosen default; ~$0.001 per decision |
| Claude Opus 5.5 (`low` effort) | 2.31 s | 3/3 | more careful reasoning; ~$0.004 per decision |
| Qwen3 4B on local Ollama (Intel Mac CPU) | ~40 s (no thinking), 10-15 min (thinking) | n/a | too slow; thinking could not be disabled through the OpenAI-compatible endpoint |

Milliseconds are only reachable with the rule-based mode; hosted LLM calls are bounded by network
round trip (~2 s). Each LLM call therefore gets a hard timeout, after which the rule decides.

## Data model (curated entry)

- `smiles`: canonical SMILES
- `structure`: optimised 3D geometry (XYZ)
- `properties`: per-method values, e.g. `{ "chemprop": ..., "xtb": ..., "dft": ... }`, with the uncertainty where available
- `provenance`: seed molecule, generator and agent step that produced it

## References

- REINVENT4 / Mol2Mol: https://github.com/MolecularAI/REINVENT4
- STONED SELFIES: https://github.com/the-matter-lab/stoned-selfies
- ChemProp: https://github.com/chemprop/chemprop
