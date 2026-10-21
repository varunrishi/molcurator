#!/bin/bash
#SBATCH --job-name=mc_gap_smoke
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=mc-gap-%j.log

set -euo pipefail
cd "${MC_REPO:?Export MC_REPO as the absolute path to the branch checkout}"
PYTHON_BIN="${MC_PYTHON:-$MC_REPO/.venv/bin/python}"
test -x "$PYTHON_BIN"
test -x "${XTB_BIN:?Export the absolute xTB executable path}"
test -x "${ORCA_BIN:?Export the absolute ORCA executable path}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MOLCURATOR_QC_TIMEOUT_S="${MOLCURATOR_QC_TIMEOUT_S:-1800}"
"$PYTHON_BIN" -c 'import rdkit, pydantic; print("RDKit", rdkit.__version__, "Pydantic", pydantic.__version__)'
git rev-parse HEAD
"$PYTHON_BIN" scripts/smoke_homo_lumo.py \
    --smiles "${MC_SMILES:-CCO}" --id "${MC_ID:-ethanol}" \
    --functional "${MC_FUNCTIONAL:-B3LYP}" --basis "${MC_BASIS:-def2-SVP}" \
    --out "${MC_OUT:-$MC_REPO/data/runs/cluster-smoke-${SLURM_JOB_ID:?}}"
