#!/bin/bash
#SBATCH --job-name=molcurator_conf
#SBATCH --partition=short
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=conf-%A_%a.log
set -euo pipefail
ROOT="${ROOT:?Pass ROOT pointing to batch directory}"
SCRIPT=/home/yo73juc/molcurator/conformer_pipeline.py
PYTHON=/home/yo73juc/miniforge3/envs/rdkit_env/bin/python
export XTB_BIN=/vast/yo73juc/miniconda3/envs/cresta/bin/xtb
export ORCA_BIN=/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
LINE=$((SLURM_ARRAY_TASK_ID+2))
IFS=, read -r NAME SMILES < <(sed -n "${LINE}p" "$ROOT/molecules.csv" | tr -d '\r')
test -n "$NAME" && test -n "$SMILES"
"$PYTHON" "$SCRIPT" --id "$NAME" --smiles "$SMILES" --out "$ROOT/conformer_runs/$NAME" --nconfs 30 --max-xtb 5 --max-orca 2
