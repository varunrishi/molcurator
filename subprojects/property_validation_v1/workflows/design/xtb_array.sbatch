#!/bin/bash
#SBATCH --job-name=MC_design_xtb
#SBATCH --partition=short
#SBATCH --time=02:59:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --output=/work/AG_Presselt/MolCurator/design_qm9_0023/xtb_%A_%a.log
set -euo pipefail
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
/home/yo73juc/miniforge3/envs/rdkit_env/bin/python -u /home/yo73juc/molcurator/molcurator_design/design.py xtb --index "$SLURM_ARRAY_TASK_ID"
