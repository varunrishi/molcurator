# MolCurator

MolCurator is an AI agent that creates and curates a benchmark set of molecules, starting from a seed molecule with a desired property.

## Idea

Given a seed molecule and a target property (e.g. a HOMO-LUMO gap range), the agent generates candidate molecules, screens them with fast ML predictions, confirms the promising ones with quantum chemistry, and assembles a curated benchmark dataset of molecules that actually have the desired property.

## Motivation

- **Benchmark dataset creation**: build property-specific molecular benchmark sets with properties computed at several levels of theory.
- **Molecular design**: support applications that need precisely tuned molecular properties, such as organic electronics and emitters.

## Approach

A small language model reasons over the workflow and calls specialised tools:

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
- **Reasoning model**: small language model, Qwen3 4B (local through Ollama by default, or any OpenAI-compatible endpoint)
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
4. sets up the **reasoning model**: starts Ollama if needed and pulls `qwen3:4b`. This step is skipped when `.env` points to a hosted endpoint, or with `--no-llm`.

At the end it lists anything it could not do automatically.

### What you may need to install yourself

- **Ollama** (for the default local model): https://ollama.com/download. You don't need it if you use a hosted LLM.
- **conda** (macOS only, for xtb): if you have neither conda nor an xtb binary, install [Miniforge](https://conda-forge.org/download/). On Linux the script downloads xtb itself.

### Choosing the LLM

The agent talks to any OpenAI-compatible endpoint, configured in `.env`:

```bash
# Default: Qwen3 4B on local Ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:4b
LLM_API_KEY=ollama

# Hosted provider or GPU server (vLLM, LM Studio, ...): nothing to install locally
LLM_BASE_URL=https://<provider>/v1
LLM_MODEL=<model name>
LLM_API_KEY=<your key>
```

On a CPU-only laptop (e.g. an Intel Mac), Qwen3 4B takes about 40 s per agent step; a GPU or hosted endpoint is much faster.

### Manual install (without the script)

```bash
uv sync                       # or: python3.11 -m venv .venv && pip install -e .
conda create -n xtb -c conda-forge xtb
cp .env.example .env          # then set XTB_BIN=$(conda run -n xtb which xtb)
ollama pull qwen3:4b
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
