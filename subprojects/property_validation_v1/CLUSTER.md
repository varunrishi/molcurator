# Pull and test the adapter on a SLURM cluster

Use the branch checkout and the dedicated adapter smoke job below. Historical scripts in `workflows/conformers/` still implement the older multi-conformer calculation policy and are not the entry point for this iteration. No LLM or API key is needed.

## 1. Get a separate checkout on the login node

```bash
git clone --branch codex/property-validation-v1 --single-branch \
  https://github.com/varunrishi/molcurator.git molcurator-property-validation
cd molcurator-property-validation
git status --short --branch
git log -1 --oneline
```

For an existing checkout of this branch, save any local edits first, then `git pull --ff-only`. Check the remote URL with `git remote -v`; use the remote pointing to `varunrishi/molcurator`. The folder name above is deliberately distinct from historical cluster deployments, so their scripts and data are preserved.

## 2. Prepare Python and external programs

With uv available, `uv sync --locked` creates the full project environment using the committed lock file (Python 3.11). Run setup/downloads where your cluster permits network access. The adapter only needs RDKit and Pydantic; an existing compatible cluster environment can instead be used through `MC_PYTHON`, since the smoke runner imports this checkout's `src` directly. Python must be 3.11 or newer and Pydantic must be v2.

```bash
uv sync --locked
export MC_REPO="$PWD"
export MC_PYTHON="$MC_REPO/.venv/bin/python"
```

Load your cluster's required ORCA/xTB modules or runtime environment before submission. Set executable paths, not directories. These paths came from the supplied research package; verify that they still exist on your cluster:

```bash
export XTB_BIN=/vast/yo73juc/miniconda3/envs/cresta/bin/xtb
export ORCA_BIN=/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca
test -x "$XTB_BIN" && test -x "$ORCA_BIN"
```

For an existing environment, replace `MC_PYTHON` with its full Python path and check:

```bash
"$MC_PYTHON" -c 'import rdkit, pydantic; print(rdkit.__version__, pydantic.__version__)'
```

There is no need to run `scripts/setup.sh`, start Ollama, or configure Anthropic for this calculation check. `.env` and the historical `config.env` are not automatically loaded by the new runner; explicitly exported variables are used.

## 3. Submit one molecule on a compute node

```bash
export MC_OUT="/work/AG_Presselt/MolCurator/adapter-smoke-$(date +%Y%m%d-%H%M%S)"
export MC_SMILES='CCO'
export MC_ID=ethanol
export MC_FUNCTIONAL=B3LYP
export MC_BASIS=def2-SVP
sbatch --partition=short --export=ALL scripts/slurm_homo_lumo_smoke.sh
```

Adapt the partition/account/QOS to your allocation. The script requests one CPU, 4 GB RAM, and two hours. Its default per-process timeout is 1800 seconds, overridable with `MOLCURATOR_QC_TIMEOUT_S`. The output directory must not already exist; each rerun needs a new directory. Each job handles exactly one molecule, one selected FF geometry, one xTB optimization, and at most one ORCA single point. It deliberately validates any successful prediction, without applying a narrow target filter: this first run checks that the programs, parsers, and geometry handoff work.

For an already allocated interactive compute node, the equivalent direct command is:

```bash
"$MC_PYTHON" scripts/smoke_homo_lumo.py --smiles 'CCO' --id ethanol \
  --functional B3LYP --basis def2-SVP --out "$MC_OUT"
```

## 4. Inspect before expanding

Read `mc-gap-JOBID.log`, `$MC_OUT/results.json`, and:

- `$MC_OUT/xyz/calculations/ethanol/xtb/geometry_report.md`: selected FF energy, sampled-set Boltzmann weight at 298.15 K.
- `$MC_OUT/xyz/calculations/ethanol/xtb/xtb.out`: converged xTB optimization and gap.
- `$MC_OUT/xyz/calculations/ethanol/orca/gap.inp` and `orca.out`: requested method, SCF convergence, orbital table, normal termination.
- `$MC_OUT/xyz/calculations/ethanol/orca/attempt.json`: one attempted QM call, success/failure.

The runner exits nonzero for a failed calculation, and `results.json` records explicit per-molecule errors. It writes prediction results before starting ORCA, so they survive an interrupted QM stage. A scheduler kill can still interrupt final reporting; inspect raw logs and attempt status too.

After ethanol succeeds, repeat separately with one representative project molecule before scaling. This runner does not implement campaign scheduling, resume, or the full agent loop. It supports only neutral closed-shell HOMO–LUMO orbital gaps; TADF remains unsupported. The historical S1 workflow and the current HOMO–LUMO adapter calculate different targets.
