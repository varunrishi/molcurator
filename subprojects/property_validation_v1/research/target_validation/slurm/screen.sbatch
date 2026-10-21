#!/usr/bin/env bash
#SBATCH --job-name=mc-screen
#SBATCH --partition=short
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --output=screen-%A_%a.out
set -euo pipefail
: "${REPO:?}" "${PANEL:?}" "${OUT:?}"
export XTB_BIN=${XTB_BIN:-/vast/yo73juc/miniconda3/envs/cresta/bin/xtb}
export MOLCURATOR_QC_TIMEOUT_S=${MOLCURATOR_QC_TIMEOUT_S:-3300}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$REPO"
"${MC_PYTHON:-$REPO/.venv/bin/python}" "$REPO/research/target_validation/screen_one.py" --manifest "$PANEL" --out "$OUT" --index "$SLURM_ARRAY_TASK_ID"
