# Run the isolated subproject on the cluster

The shared main project is unchanged. This branch contains the contribution entirely within `subprojects/property_validation_v1/`.

## Checkout and isolated installation

```bash
git clone --branch codex/calibrated-screening-v1 --single-branch \
  https://github.com/varunrishi/molcurator.git molcurator-calibrated-screening
cd molcurator-calibrated-screening/subprojects/property_validation_v1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e ../..
python -m pip install -e '.[test,reports,viewers]'
python -m pytest -q tests
```

Root contracts and this subproject are installed into this separate environment. Full root `uv sync` is not required for this chemistry contribution. For an existing checkout, save local work, then `git pull --ff-only` on this branch before entering the subproject directory.

## One-molecule SLURM check

Load the cluster's required runtime modules and verify these historical binary paths:

```bash
export XTB_BIN=/vast/yo73juc/miniconda3/envs/cresta/bin/xtb
export ORCA_BIN=/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca
export MC_SUBPROJECT="$PWD"
export MC_PYTHON="$PWD/.venv/bin/python"
export MC_OUT="/work/AG_Presselt/MolCurator/adapter-smoke-$(date +%Y%m%d-%H%M%S)"
test -x "$XTB_BIN" && test -x "$ORCA_BIN"
sbatch --partition=short --export=ALL scripts/slurm_homo_lumo_smoke.sh
```

`MC_SUBPROJECT` must point to this subproject directory, not the repository root. Adjust partition/account/QOS for the allocation. The job requests one CPU, 4 GB RAM and two hours. It defaults to ethanol, B3LYP/def2-SVP, and a 1800-second timeout per external process. Optional overrides: `MC_SMILES`, `MC_ID`, `MC_FUNCTIONAL`, `MC_BASIS`, `MOLCURATOR_QC_TIMEOUT_S`.

For an allocated interactive compute node, run:

```bash
"$MC_PYTHON" scripts/smoke_homo_lumo.py --smiles 'CCO' --id ethanol \
  --functional B3LYP --basis def2-SVP --out "$MC_OUT"
```

Use a new output directory for each smoke run. Inspect `results.json`, the SLURM log, and `xyz/calculations/ethanol/` beneath the output directory. The xTB folder contains geometry/Boltzmann reports; ORCA's folder contains the input, output and latest attempt record. A failed calculation exits nonzero. Inspect one molecule and then a representative project molecule before expanding.

For research array jobs, set `REPO` to the subproject directory and `MC_PYTHON` to its environment Python. The preserved historical `workflows/` scripts use the older multi-conformer policy; use the dedicated smoke job or the isolated package for the current policy. No LLM/API key is needed.
