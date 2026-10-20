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
- **Reasoning model**: small language model, Qwen3 4B
- **Molecular generation**: [RDKit](https://www.rdkit.org/) plus the pretrained Mol2Mol model ([REINVENT4](https://github.com/MolecularAI/REINVENT4)), or stochastic molecular evolution with [STONED SELFIES](https://github.com/the-matter-lab/stoned-selfies)
- **Property prediction (ML)**: [ChemProp](https://github.com/chemprop/chemprop)
- **Semi-empirical**: xTB
- **Quantum chemistry**: [PySCF](https://pyscf.org/) or [ORCA](https://www.faccts.de/orca/)

## Installation

Requires Python 3.11 or newer.

### 1. Python package

With [uv](https://docs.astral.sh/uv/) (recommended; uses the pinned versions in `uv.lock`):

```bash
git clone git@github.com:varunrishi/molcurator.git
cd molcurator
uv sync                 # creates .venv/ with all dependencies, including dev tools
source .venv/bin/activate
```

Or with pip:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Intel Macs, PyTorch is capped at 2.2.2 (the last release with Intel-Mac wheels), which also caps NumPy below 2 and RDKit below 2026. This is handled automatically.

### 2. xtb (external binary)

xtb is not available on PyPI, so install the binary separately:

**conda-forge (recommended, prebuilt for Linux and macOS):** put xtb in its own small conda environment, kept apart from the uv `.venv`, and point `XTB_BIN` at it:

```bash
conda create -n xtb -c conda-forge xtb
export XTB_BIN="$(conda run -n xtb which xtb)"   # add to your shell profile
"$XTB_BIN" --version
```

**Homebrew:** `brew tap grimme-lab/qc && brew install xtb`. Newer Homebrew versions also need you to trust the tap's formulas (`brew trust`), and on Intel Macs they build from source.

You can also download a release from https://github.com/grimme-lab/xtb/releases. MolCurator uses `XTB_BIN` if it is set, and otherwise looks for `xtb` on your `PATH`.

### 3. Reasoning model (Qwen3 4B)

The agent talks to Qwen3 4B through [Ollama](https://ollama.com/):

```bash
ollama pull qwen3:4b
ollama serve            # if the Ollama app is not already running
```

### 4. Optional

- **ORCA**: an alternative to PySCF for VALIDATE. It needs a free academic licence and is downloaded from https://orcaforum.kofo.mpg.de.
- **REINVENT4 (Mol2Mol)**: an alternative generator; install it from https://github.com/MolecularAI/REINVENT4. STONED SELFIES is the default and is installed with the package.

### Check the install

```bash
python -c "import rdkit, pyscf, chemprop, selfies, langgraph; print('ok')"
"${XTB_BIN:-xtb}" --version
```

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
