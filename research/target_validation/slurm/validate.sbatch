#!/usr/bin/env bash
#SBATCH --job-name=mc-valid
#SBATCH --partition=short
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=validate-%A_%a.out
set -euo pipefail
: "${REPO:?}" "${PANEL:?}" "${OUT:?}"
export ORCA_BIN=${ORCA_BIN:-/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca}
export MOLCURATOR_QC_TIMEOUT_S=${MOLCURATOR_QC_TIMEOUT_S:-6900}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$REPO"
"$REPO/.venv/bin/python" "$REPO/research/target_validation/validate_one.py" --manifest "$PANEL" --out "$OUT" --index "$SLURM_ARRAY_TASK_ID"
