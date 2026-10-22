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
| `PREDICT`  | SMILES → MMFF94 geometry → GFN2-xTB property (or B97-3c TD-DFT when xTB cannot give it, e.g. S1-T1) |
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
- **Semi-empirical**: GFN2-xTB through [tblite](https://github.com/tblite/tblite)'s Python API (no binary)
- **Quantum chemistry**: [ORCA](https://www.faccts.de/orca/) 6.1.1+, driven from Python by OPI (`orca-pi`)

## Installation

### Quick start

```bash
git clone git@github.com:varunrishi/molcurator.git
cd molcurator
scripts/setup.sh
source .venv/bin/activate
```

`scripts/setup.sh` is safe to re-run. It:

1. creates `.env` from `.env.example` (settings for ORCA and the LLM; values already set in your environment take precedence);
2. installs [uv](https://docs.astral.sh/uv/) if needed and runs `uv sync` (Python 3.11 and all dependencies, pinned in `uv.lock`). This includes xTB, through tblite;
3. looks for **ORCA** (`ORCA_BIN` or `orca` on `PATH`) and **Open MPI** (`OPENMPI_HOME`, `mpirun` on `PATH`, or a conda env) and saves their paths to `.env`. ORCA cannot be installed by the script;
4. sets up the optional **local model**: starts Ollama if needed and pulls `qwen3:4b`. Skip it with `--no-llm`; the default Claude backend only needs `ANTHROPIC_API_KEY` in `.env`.

At the end it lists anything it could not do automatically.

### What you may need to install yourself

- **An Anthropic API key** for the default decision model: add `ANTHROPIC_API_KEY=...` to `.env` (gitignored). Without it, runs can use rule-based decisions.
- **Ollama** (optional, for a local model): https://ollama.com/download.
- **ORCA** (quantum chemistry): install ORCA 6.1.1 or newer (free academic licence, https://orcaforum.kofo.mpg.de), then set `ORCA_BIN=/path/to/orca` in `.env`. It is needed when the run config has a `qm:` section (VALIDATE), and for PREDICT on targets xTB cannot give (`s1_t1_gap`). HOMO-LUMO runs without QM need only xTB, which comes with the Python dependencies. Runs on more than one ORCA core (`orca_nprocs` in the chemistry settings) also need Open MPI: set `OPENMPI_HOME` in `.env` to the folder holding `bin/mpirun` (for example a conda env with `openmpi`), or put `mpirun` on `PATH`; `setup.sh` looks for one. Parallel runs use single-node shared-memory transport with UCX off by default (any `OMPI_MCA_*` you set wins). The PySCF backend is not implemented yet.

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
cp .env.example .env          # then set ORCA_BIN=/path/to/orca if you use ORCA
# add ANTHROPIC_API_KEY to .env
```

On Intel Macs, PyTorch is capped at 2.2.2 (the last release with Intel-Mac wheels), which also caps NumPy below 2 and RDKit below 2026. This is handled automatically, but it leaves out OPI (`orca-pi` needs NumPy 2), so ORCA calculations are unavailable there.

### Windows (and any machine, with conda)

`scripts/setup.sh` is a bash script and `uv sync` cannot install xTB on Windows: tblite (xTB) has
no Windows wheels on PyPI. [`environment.yml`](environment.yml) installs it from conda-forge
instead, which has Windows builds, and then installs everything else from PyPI with pip:

```bash
conda env create -f environment.yml     # Miniforge: https://conda-forge.org/download/
conda activate molcurator
copy .env.example .env                  # PowerShell / cmd; cp on Linux and macOS
```

The same file works on Linux and macOS as an alternative to `uv sync`. tblite comes from
conda-forge on every platform, and pip finds it already installed; outside conda, `pyproject.toml`
installs tblite from PyPI on Linux and macOS. pip does not read `uv.lock`, so this environment gets
the newest versions `pyproject.toml` allows rather than the locked ones.

On Windows:

- **ORCA**: install the Windows build, then set `ORCA_BIN` in `.env` to `orca.exe` or its folder.
- **One ORCA core only**: keep `orca_nprocs: 1`. Parallel ORCA on Windows uses Microsoft MPI, which
  the tools do not set up.
- **Without tblite** (for example a plain `pip install -e .`), GFN2-xTB runs through ORCA's built-in xTB.
- **Untested**: the conda packages and the code paths exist for Windows, but this setup has not been
  run on a Windows machine yet.

### Optional

- **REINVENT4 (Mol2Mol)**: an alternative generator; install it from https://github.com/MolecularAI/REINVENT4. STONED SELFIES is the default and is installed with the package.

## Running the agent

```bash
molcurator run -c configs/homo_lumo.yaml
```

The agent works in rounds. Each round it:
1. generates candidates from the best molecules so far, starting from the seeds in the config
2. runs xTB on a random sample of them (`predict.n_xtb`)
3. trains an ML model once enough xTB values exist (`train.min_examples`), and scores the rest with it
4. screens the candidates against the target window
5. with QM on only: sends the screened candidates closest to the target to QM (VALIDATE)
6. adds hits to the dataset

It stops when the dataset reaches `budget.target_dataset_size`, or when another budget runs out:
`max_rounds`, `max_qm_calls` or `max_wall_time`.

**QM is optional.** It runs only when the config has a `qm:` section naming the method, as
commented out in `configs/homo_lumo.yaml`:

```yaml
qm:
  backend: orca
  functional: B3LYP
  basis: def2-SVP
```

**Targets.** `target.name` can be any single-number property the tools compute: `homo_lumo_gap`,
`s1_t1_gap`, `s1_energy`, `t1_energy`, `s0_t1_gap`, `ionization_potential`, `electron_affinity`,
`dipole_moment`, `polarizability`, `g_tensor`, `energy` or `thermochemistry`. Give the window in that
property's unit (eV for gaps and excitation energies, debye, bohr^3, Eh). `target.units` can be left out
and is filled in. A name the tools do not compute, or a unit that does not match, is refused when the
config loads.

**Levels of theory.** VALIDATE uses `qm.functional` / `qm.basis`. PREDICT defaults to GFN2-xTB, or
B97-3c TD-DFT for targets xTB cannot give (S1-T1); set `predict.method` / `predict.basis` to change it:

```yaml
predict:
  method: PBE0        # any ORCA method, or gfn2-xtb / gfn1-xtb
  basis: def2-SVP     # only for methods without their own basis (not xTB or "-3c" methods)
```

The config is refused when it loads if the choice cannot work: xTB for an S1-T1 target, a basis
for a method with its own, or the same level for PREDICT and VALIDATE. The batch command takes
`--predict-method` / `--predict-basis` and `--functional` / `--basis` for the same settings.

With QM on:
- SELECT QM BATCH and VALIDATE run between SCREEN and CURATE.
- Only QM-validated molecules inside the target window are curated.
- `budget.max_qm_calls` caps the number of QM calculations, one per molecule. The rules spread it
  evenly: each round gets calls left ÷ rounds left, and calls a round doesn't use go to later rounds.
- A molecule chosen for QM that has only an ML value gets xTB first, for a starting geometry. If
  that xTB fails, it skips QM.

`enabled: false` keeps the section but skips QM.

Each step prints a line when it finishes:

```
Run 20261021-201525-7864 started
r1 plan_round Rule: repeat the previous settings with the best parents so far. (0.0 s)
r1 generate generated 100 (0.1 s)
r1 predict predicted 98 · failed 2 (38.8 s)
r1 train skipped: below_min_examples
r1 ml_predict skipped: no_candidates_left
r1 screen screened_out 81 · screened_in 17 (0.0 s)
r1 curate curated 9 (0.0 s)
r1 close_round generated 100 · xTB 100 · ML 0 · screened in 17 · hits 9 (0.0 s)
r1 continue_or_stop Rule: budget remains. (0.0 s)
...
Run 20261021-201525-7864 stopped: target_dataset_size. Dataset size: 28.
```

Options:
- `--run-id <name>` names the run folder. An existing run is never overwritten.
- `--runs-root <dir>` changes where run folders go (default `data/runs`).
- `--resume <run_id>` continues an interrupted run (e.g. stopped with Ctrl-C) from its last finished
  step, using the run's saved config. Time spent stopped does not count against `max_wall_time`.

The command exits with code 1 if a step crashed. The error is printed and saved in the trace and
summary.

**Outputs**, in `data/runs/<run_id>/`:

| File | Contents |
|---|---|
| `dataset.csv` | the curated molecules: id, SMILES, XYZ path, values at each level (`ml`, `xtb`, `qm` with `qm_method`), whether QM-validated, and provenance (parent, round, generator, seeds) |
| `dataset_ml_only.csv` | the curated molecules that have only an ML value (no xTB or QM): id, SMILES, `ml` and provenance. Written once at the end of the run, from `dataset.csv` |
| `xyz/` | the MMFF94 geometries PREDICT and VALIDATE computed at; `xyz/calculations/<id>/` holds each molecule's geometry report, `predict.json` and `validate.json` records and ORCA files |
| `models/` | trained ML models, one folder per round |
| `traces/trace.jsonl` | one JSON line per step; see [`docs/trace-format.md`](docs/trace-format.md) |
| `summary.md` | a short report of the run and why it stopped |
| `config.yaml` | the exact settings the run used |
| `checkpoint.sqlite` | the agent state after every step, for `--resume` |

**Current limits (v1):**
- **Decisions use rules** (`decisions: rules` in the configs). Set `decisions: llm` to have Claude Haiku 4.5 plan
  rounds, decide whether to continue and write the summary; it needs `ANTHROPIC_API_KEY` in `.env`, and the
  rules take over whenever an answer is invalid or late.
- **QM is off in the shipped configs** (their `qm:` sections are commented out). With QM on, there is no
  human approval step before QM yet (`--approve-qm`), and `decisions: llm` still uses the rule to choose
  the QM batch. The trajectory evaluator reports QM runs as `not_assessable`.
- **Molecules screened in by ML alone are curated too,** with an empty `xtb` column in `dataset.csv`, and
  are also listed on their own in `dataset_ml_only.csv`. TRAIN learns only from xTB values, never from ML
  predictions, and starts once `train.min_examples` (150) xTB values exist. Its test MAE is about 0.5 eV and
  it rarely picks molecules inside the target window correctly, so treat ML-only rows as candidates to check,
  not confirmed hits.

From Python:

```python
from molcurator.agent.runner import run_agent
from molcurator.config import load_config

state = run_agent(load_config("configs/homo_lumo.yaml"))
```

[`notebooks/run_agent.ipynb`](notebooks/run_agent.ipynb) walks through one small run with the real tools (about 2
minutes) and its results: round stats, `dataset.csv`, the summary and the curated molecules.

## Property tools and batch runs

The chemistry behind PREDICT and VALIDATE is two tool-call functions that take a geometry, a
property name and a level of theory, and return a JSON-ready dict (`success`, `value`, `unit`,
`details`, `method`, `notes`, `error`). Each also exports `tool_definition()`, an LLM tool schema.

- `molcurator.chem.orca.calculate_property`: ORCA through OPI, at any ORCA method. Energies,
  gradients, optimisation, frequencies, thermochemistry, HOMO-LUMO gap, dipole, charges,
  polarizability, NMR shieldings, g-tensor, TD-DFT excited states (S1, T1, S1-T1 gap), and delta-SCF
  ionisation potentials and electron affinities.
- `molcurator.chem.xtb.calculate_property`: GFN2-, GFN1- and IPEA1-xTB through tblite, in-process.
  Energies, gradients, optimisation, frequencies, HOMO-LUMO gap, dipole, quadrupole, charges, bond
  orders, IP/EA, with optional ALPB solvation. xTB has no excited states. Where tblite is not
  installed (it is left out on Windows, which has no tblite wheels), GFN2-/GFN1-xTB fall back to
  ORCA's built-in xTB (same numbers; the result's notes say so).

VALIDATE refuses xTB methods (`qm.functional: gfn2-xtb` is rejected when the config is loaded):
it has to be a higher level of theory than PREDICT, which runs GFN2-xTB wherever xTB can give the target.

`molcurator-properties` runs the same PREDICT (and optionally VALIDATE) over a CSV or SMILES file,
outside the agent loop:

```bash
molcurator-properties run generated.csv --out data/runs/batch-001                       # HOMO-LUMO gap, xTB
molcurator-properties run generated.csv --out data/runs/batch-002 --property s1_t1_gap \
    --max 0.3 --orca --functional PBE0                                                   # TD-DFT, then QM
molcurator-properties report data/runs/batch-001 --plots                                 # rebuild reports
molcurator-properties slurm --config configs/slurm.json --script job.sbatch              # cluster script
```

Runtime settings (conformers, ORCA cores and memory, timeout) come from the JSON file named by
`MOLCURATOR_CHEM_CONFIG` (start from `configs/chemistry.example.json`); set `orca_nprocs` above 1
for parallel ORCA runs (needs Open MPI, see above).
`python scripts/check_property_tools.py [--smoke --out DIR]` checks the setup.

## Project structure

```
src/molcurator/
├── tools/       GENERATE, PREDICT, TRAIN, VALIDATE, CURATE, EVALUATE (one module each)
├── agent/       LangGraph graph, agent state, LLM client, prompts
├── chem/        SMILES/SELFIES conversion, 3D geometry and XYZ I/O, and the property tools:
│                orca.py (ORCA via OPI), xtb.py (xTB via tblite), backends.py (picks one)
├── batch/       `molcurator-properties` command: PREDICT/VALIDATE over a file, reports, SLURM
├── schemas.py   shared data models (Candidate, PropertyValue, CuratedEntry)
└── cli.py       `molcurator` command
configs/         one YAML file per use case (homo_lumo.yaml, tadf.yaml), example chemistry/SLURM settings
data/seeds/      seed molecules
data/properties/ shared xTB/ORCA property dataset (PROPERTY_DATA.md)
data/runs/       per-run outputs (gitignored)
docs/chemistry/  guides from the earlier xtb-binary implementation (superseded; see Property tools above)
research/        study results, e.g. the local xTB validation report
tests/           tool tests, plus tests/agent/ for the agent
notebooks/       exploration and demo plots
scripts/         helper scripts
demo/            presentation and video assets
assets/          logo and README images
```
## Troubleshooting

- **xTB not available:** xTB runs through tblite, a Python dependency (`uv sync`; on Windows, `environment.yml`). Without tblite, GFN2-/GFN1-xTB fall back to ORCA's built-in xTB. `python scripts/check_property_tools.py` reports which engine is used.
- **Missing `ANTHROPIC_API_KEY`:** add `ANTHROPIC_API_KEY=...` to `.env`, or set `decisions: rules` in the run config so no LLM is called.
- **ORCA not found:** set `ORCA_BIN=/path/to/orca` in `.env`. ORCA is needed when the config has a `qm:` section, and for PREDICT on targets xTB cannot give (`s1_t1_gap`); the PySCF backend is not implemented.
- **Run interrupted (e.g. Ctrl-C):** continue with `molcurator run --resume <run_id>`. The run's saved config is used.
- **Local model (Ollama) is slow:** a CPU-only laptop takes about 40 s per decision with Qwen3 4B. Use the default Claude backend or `decisions: rules` instead.

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
