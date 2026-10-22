# Contributing to MolCurator

This guide is for teammates building the tools (GENERATE, PREDICT, VALIDATE, CURATE) and anyone
else adding to the repo. The one idea to keep in mind:

> **Every tool is a single Python function with a fixed signature.** Everything else in the repo
> either defines that contract or calls it. You can build and test your tool without knowing how
> the agent works.

## How the pieces fit

The agent runs a fixed loop; the tools are the steps in capitals:

```
plan round [LLM] -> GENERATE -> PREDICT (xTB) -> SCREEN (rule) -> select QM batch [LLM]
  -> VALIDATE (QM) -> CURATE -> continue or stop [LLM] -> next round, or summary
```

The agent (orchestrator) is developed on the `agent/orchestrator` branch. It calls your tool
only through its signature, so the two can be built in parallel.

## Where things live

| Path | What it is | Who changes it |
|---|---|---|
| `src/molcurator/tools/<tool>.py` | **your tool**: one function | the tool's owner |
| `src/molcurator/schemas.py` | **the contract**: data models every tool takes and returns | everyone reads; change only by a separate PR (see below) |
| `src/molcurator/chem/` | shared chemistry helpers (SMILES/SELFIES, STONED, geometry) | tool owners, shared |
| `tests/test_<tool>.py` | your tool's tests | the tool's owner |
| `tests/agent/fakes.py` | fake versions of all four tools: the clearest example of what the agent expects back | read only |
| `configs/*.yaml` | the two use cases (HOMO-LUMO gap, TADF) | rarely |
| `src/molcurator/agent/` | the orchestrator | agent owner |
| `.claude/specs/` | mission, roadmap, tech stack, phase specs | read for context |
| `scripts/setup.sh`, `.env.example` | one-command setup; per-machine settings | everyone runs setup once |

## Setup

```bash
git clone git@github.com:varunrishi/molcurator.git
cd molcurator
scripts/setup.sh            # uv + Python deps (xTB via tblite), ORCA check, .env; safe to re-run
source .venv/bin/activate
```

Per-machine settings go in `.env` (gitignored): `ORCA_BIN`, `OPENMPI_HOME`, `ANTHROPIC_API_KEY`, `MOLCURATOR_CHEM_CONFIG`.
See the README for details.

## The tool contract

The signatures in `src/molcurator/tools/*.py` are fixed:

```python
generate(parents: list[str], settings: GenerationSettings, round: int, rng_seed: int) -> list[Candidate]
predict(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]
validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]
curate(entries: list[CuratedEntry], run_dir: Path) -> int   # returns the dataset size
```

Rules every tool must follow (the models in `schemas.py` enforce some of them):

1. **One result per input molecule, in the same order, never dropped.** A molecule that fails
   comes back with `status="failed"` and an `error` message. The agent stops the run if a tool
   returns too few, too many or unknown ids.
2. **`ok` results carry a value; `failed` results carry an error and no value.**
3. **Deterministic:** the same inputs (including `rng_seed`) give the same output.
4. **Canonical SMILES** (RDKit), so molecules can be compared as strings.

Tool-specific obligations:

- **GENERATE** (done, STONED SELFIES): only RDKit-valid molecules; ids unique within the run,
  e.g. `r{round}-c{index:03d}`. Use `tools/generate.py` as the worked example.
- **PREDICT** (done): MMFF94 geometry, then GFN2-xTB through tblite (`chem/xtb.py`), or B97-3c
  TD-DFT through ORCA (`chem/orca.py`) for targets xTB cannot give, such as the S1-T1 gap.
  Writes each geometry to `xyz_dir/<id>.xyz` and returns the path.
- **VALIDATE** (done, ORCA driven from Python by OPI / `orca-pi`; PySCF not implemented): starts
  from each molecule's PREDICT geometry, and names the level of theory in `method`
  (e.g. `"dft:B3LYP/def2-SVP"`). New target properties go in `chem/orca.py` / `chem/xtb.py`.
  xTB methods are refused in VALIDATE, which must be above PREDICT's level of theory.
- **CURATE:** must be **idempotent**: an entry whose id or SMILES is already in the dataset is
  skipped, so re-running after an interrupted run never adds a molecule twice.

When in doubt, compare against `FakeTools` in `tests/agent/fakes.py`: it follows the same
contract and shows exactly the shape the agent receives.

## Workflow

1. **Branch from `main`:** `git switch -c tools/<tool> origin/main` (e.g. `tools/predict-xtb`).
2. **Stay in your lane:** your tool file, its tests, and `chem/` helpers.
3. **Test your tool on its own:** `uv run pytest tests/test_<tool>.py`. You don't need the agent,
   an LLM key or the other tools.
4. **Keep up to date:** merge `main` into your branch regularly (`git fetch origin && git merge origin/main`).
5. **Open a PR to `main`** when your tool's tests pass. `main` only changes through PRs.

### Changing the contract

Any change to `schemas.py` or a tool signature affects everyone. Make it in **its own small PR
to `main`**, separate from tool work, and tell the team. Don't bury it inside a tool branch.

## Known open items

- `tools/generate.py` caps candidates at 15 heavy atoms, which is too small for TADF emitters.
  The planned fix is a per-config `max_heavy_atoms` in the contract.
- ORCA must be a current release installed by hand, with `ORCA_BIN` set in `.env`.
- The seed molecules in `configs/homo_lumo.yaml` and `configs/tadf.yaml` are placeholders.
