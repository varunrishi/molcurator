#!/usr/bin/env bash
#SBATCH --job-name=mc_cal24
#SBATCH --partition=short
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=slurm-cal-%A_%a.out
set -euo pipefail
: "${REPO:?set REPO}" "${PANEL:?set PANEL}" "${OUT:?set OUT}"
export XTB_BIN=${XTB_BIN:-/vast/yo73juc/miniconda3/envs/cresta/bin/xtb}
export ORCA_BIN=${ORCA_BIN:-/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca}
export MOLCURATOR_QC_TIMEOUT_S=${MOLCURATOR_QC_TIMEOUT_S:-5400}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$REPO"
"$REPO/.venv/bin/python" "$REPO/research/calibration24/run_one.py" --manifest "$PANEL" --out "$OUT" --index "$SLURM_ARRAY_TASK_ID"
