<p align="center">
  <img src="assets/logo.png" alt="MolCurator logo" width="320">
</p>

# MolCurator

MolCurator is an AI agent that creates and curates a benchmark set of molecules, starting from a seed molecule with a desired property.

## Idea

Given a seed molecule and a target property (e.g. a HOMO-LUMO gap range), the agent generates candidate molecules, screens them with fast ML predictions, confirms the promising ones with quantum chemistry, and assembles a curated benchmark dataset of molecules that actually have the desired property.

## Motivation

- **Benchmark dataset creation**: build property-specific molecular benchmark sets with properties computed at several levels of theory.
- **Molecular design**: support applications that need precisely tuned molecular properties, such as organic electronics and emitters.

## Approach

The workflow is a fixed sequence of tool steps. A fast language model (Claude Haiku 4.5 by default) makes the decisions inside it: how to generate each round, which candidates get quantum chemistry, and when to stop. Every decision also has a rule-based fallback.

1. **Generate**: create candidate molecules from the seed molecule.
2. **Screen**: predict the target property with an ML model and keep candidates that meet the threshold values.
3. **Validate**: for the screened candidates, use the prediction uncertainty to pick which ones to confirm with quantum chemistry calculations.
4. **Curate**: store each verified molecule with its SMILES, 3D structure and a set of properties computed by methods of different accuracy.

```
seed molecule + target property
        │
        ▼
   GENERATE ──► PREDICT / SCREEN (ML + uncertainty) ──► VALIDATE (QM) ──► CURATE ──► benchmark set
        ▲                    │                                               │
        └──── TRAIN (retrain ML model on the growing dataset) ◄──────────────┘
```

## Tools

| Tool | Purpose |
|------|---------|
| `GENERATE` | Generate new molecules (SMILES / coordinates) from a seed molecule |
| `PREDICT`  | SMILES → 3D geometry → xTB optimisation → property extraction |
| `TRAIN`    | Train ML models (e.g. ChemProp) for the target property on the growing dataset |
| `VALIDATE` | Compute the property for screened molecules with more accurate quantum chemistry methods |
| `CURATE`   | Add verified molecules to the dataset with SMILES, structure and multi-level properties |
| `EVALUATE` | Evaluate the agent's trajectories and tool calls |

## Use cases

- Molecules within a specific **HOMO-LUMO gap** range.
- Candidate **TADF emitters** (thermally activated delayed fluorescence), with an S1-T1 gap close to zero.

## Software stack

- **Orchestrator**: [LangGraph](https://github.com/langchain-ai/langgraph)
- **Decision model**: [Claude Haiku 4.5](https://docs.claude.com/) through the Anthropic SDK (~2 s per decision); optionally any OpenAI-compatible endpoint, such as a local model in Ollama
- **Molecular generation**: [RDKit](https://www.rdkit.org/) plus the pretrained Mol2Mol model ([REINVENT4](https://github.com/MolecularAI/REINVENT4)), or stochastic molecular evolution with [STONED SELFIES](https://github.com/the-matter-lab/stoned-selfies)
- **Property prediction (ML)**: [ChemProp](https://github.com/chemprop/chemprop)
- **Semi-empirical**: xTB
- **Quantum chemistry**: [PySCF](https://pyscf.org/) or [ORCA](https://www.faccts.de/orca/)

## Installation

### Quick start

```bash
git clone git@github.com:varunrishi/molcurator.git
cd molcurator
scripts/setup.sh
source .venv/bin/activate
```

`scripts/setup.sh` is safe to re-run. It:

1. creates `.env` from `.env.example` (settings for xtb and the LLM; values already set in your environment take precedence);
2. installs [uv](https://docs.astral.sh/uv/) if needed and runs `uv sync` (Python 3.11 and all dependencies, pinned in `uv.lock`);
3. finds or installs **xtb**: an existing `XTB_BIN` or `xtb` on `PATH`, else a conda-forge env named `xtb` (if conda, mamba or micromamba is installed), else the official Linux release in `.tools/`. The path is saved to `.env`;
4. sets up the optional **local model**: starts Ollama if needed and pulls `qwen3:4b`. Skip it with `--no-llm`; the default Claude backend only needs `ANTHROPIC_API_KEY` in `.env`.

At the end it lists anything it could not do automatically.

### What you may need to install yourself

- **An Anthropic API key** for the default decision model: add `ANTHROPIC_API_KEY=...` to `.env` (gitignored). Without it, runs can use rule-based decisions.
- **Ollama** (optional, for a local model): https://ollama.com/download.
- **conda** (macOS only, for xtb): if you have neither conda nor an xtb binary, install [Miniforge](https://conda-forge.org/download/). On Linux the script downloads xtb itself.

### Choosing the LLM

Decisions are made by Claude Haiku 4.5 by default, configured in `.env`:

```bash
# Default: Claude Haiku 4.5 through the Anthropic API (~2 s per decision)
ANTHROPIC_API_KEY=<your key>
LLM_PROVIDER=anthropic
LLM_MODEL=claude-haiku-4-5

# Optional: any OpenAI-compatible endpoint, e.g. a local model in Ollama
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:4b
LLM_API_KEY=ollama
```

For tests and fast development runs, set `decisions: rules` in the run config: every decision then uses its rule (<1 ms) and no LLM is called. A local model on a CPU-only laptop is slow (Qwen3 4B: ~40 s per decision, or minutes with thinking on).

### Manual install (without the script)

```bash
uv sync                       # or: python3.11 -m venv .venv && pip install -e .
conda create -n xtb -c conda-forge xtb
cp .env.example .env          # then set XTB_BIN=$(conda run -n xtb which xtb)
# add ANTHROPIC_API_KEY to .env
```

On Intel Macs, PyTorch is capped at 2.2.2 (the last release with Intel-Mac wheels), which also caps NumPy below 2 and RDKit below 2026. This is handled automatically.

### Optional

- **ORCA**: an alternative to PySCF for VALIDATE. It needs a free academic licence and is downloaded from https://orcaforum.kofo.mpg.de.
- **REINVENT4 (Mol2Mol)**: an alternative generator; install it from https://github.com/MolecularAI/REINVENT4. STONED SELFIES is the default and is installed with the package.

## Project structure

```
src/molcurator/
├── tools/       GENERATE, PREDICT, TRAIN, VALIDATE, CURATE, EVALUATE (one module each)
├── agent/       LangGraph graph, agent state, LLM client, prompts
├── chem/        shared helpers: SMILES/SELFIES conversion, 3D geometry, XYZ I/O
├── schemas.py   shared data models (Candidate, PropertyValue, CuratedEntry)
└── cli.py       `molcurator` command
configs/         one YAML file per use case (homo_lumo.yaml, tadf.yaml)
data/seeds/      seed molecules
data/runs/       per-run outputs (gitignored)
tests/           one test file per tool
notebooks/       exploration and demo plots
scripts/         helper scripts
demo/            presentation and video assets
assets/          logo and README images
```

## Roadmap

| Day | Date | Goal |
|-----|------|------|
| 1 | 20 Oct 2026 | Build the basic structure of each tool: GENERATE, PREDICT, TRAIN, VALIDATE, CURATE, EVALUATE |
| 2 | 21 Oct 2026 | Connect the tools to the LangGraph orchestrator and test on the HOMO-LUMO gap and TADF use cases |
| 3 | 22 Oct 2026 | Prepare the demo presentation and record a short project video |

## References

- Mol2Mol / REINVENT4: https://github.com/MolecularAI/REINVENT4
- STONED SELFIES: https://github.com/the-matter-lab/stoned-selfies
- ChemProp: https://github.com/chemprop/chemprop

## License

See [LICENSE](LICENSE).
