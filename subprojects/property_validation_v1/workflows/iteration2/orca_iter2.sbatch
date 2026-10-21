#!/bin/bash
#SBATCH --job-name=molcurator-i2-orca
#SBATCH --partition=short
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:30:00
#SBATCH --output=/work/AG_Presselt/MolCurator/design_iteration2/orca_%A_%a.log
set -euo pipefail
/home/yo73juc/miniforge3/envs/rdkit_env/bin/python /home/yo73juc/molcurator/molcurator_iteration2/iteration2.py orca --index "${SLURM_ARRAY_TASK_ID}"
