# Tech Stack

## Agent layer

| Component | Choice | Role |
|-----------|--------|------|
| Orchestrator | [LangGraph](https://github.com/langchain-ai/langgraph) | Stateful agent graph; routes between tools and holds the loop state |
| Reasoning model | Qwen3 4B (small language model) through any OpenAI-compatible endpoint (`langchain-openai`); default is local Ollama, a hosted endpoint is a `.env` change | Plans the next step, picks tools, interprets results |

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
- Python dependencies: langgraph, langchain-core, langchain-openai, rdkit, selfies, pyscf, chemprop (brings torch + lightning), pandas, pydantic, pyyaml, typer, python-dotenv
- Intel-Mac limits, set with platform markers in `pyproject.toml`: torch 2.2.2 (the last Intel-Mac wheel), so `numpy<2` and `rdkit<2026`. Other platforms get current versions.
- External binaries (not on PyPI):
  - **xtb**: found or installed by `setup.sh`: existing `XTB_BIN` / `PATH`, else a conda-forge env named `xtb`, else the Linux release in `.tools/` (Homebrew also works by hand); the path is saved as `XTB_BIN` in `.env`
  - **Ollama**: serves `qwen3:4b` locally (CPU-only laptops: ~40 s per call); not needed with a hosted endpoint
- Settings: `.env` (gitignored, created from `.env.example`): `XTB_BIN`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`; variables already in the environment take precedence
  - **ORCA** (optional): needs a licence
  - **REINVENT4** (optional): Mol2Mol generator, installed from its git repo

## Project structure

```
molcurator/
├── pyproject.toml / uv.lock / .python-version / .env.example
├── src/molcurator/
│   ├── tools/            generate.py, predict.py, train.py, validate.py, curate.py, evaluate.py
│   ├── agent/            graph.py (LangGraph), state.py, llm.py (OpenAI-compatible client), prompts.py
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

## Data model (curated entry)

- `smiles`: canonical SMILES
- `structure`: optimised 3D geometry (XYZ)
- `properties`: per-method values, e.g. `{ "chemprop": ..., "xtb": ..., "dft": ... }`, with the uncertainty where available
- `provenance`: seed molecule, generator and agent step that produced it

## References

- REINVENT4 / Mol2Mol: https://github.com/MolecularAI/REINVENT4
- STONED SELFIES: https://github.com/the-matter-lab/stoned-selfies
- ChemProp: https://github.com/chemprop/chemprop
