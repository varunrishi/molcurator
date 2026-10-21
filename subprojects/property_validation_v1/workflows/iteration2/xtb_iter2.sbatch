#!/bin/bash
#SBATCH --job-name=molcurator-i2-xtb
#SBATCH --partition=short
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=02:30:00
#SBATCH --output=/work/AG_Presselt/MolCurator/design_iteration2/xtb_%A_%a.log
set -euo pipefail
/home/yo73juc/miniforge3/envs/rdkit_env/bin/python /home/yo73juc/molcurator/molcurator_iteration2/iteration2.py xtb --index "${SLURM_ARRAY_TASK_ID}"
