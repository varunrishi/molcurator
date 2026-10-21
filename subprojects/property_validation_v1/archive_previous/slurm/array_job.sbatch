#!/usr/bin/env bash
#SBATCH --job-name=molcurator
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:30:00
set -euo pipefail
: "${MC_REPO:?}" "${MC_OPERATION:?}" "${MC_PYTHON:?}" "${SLURM_ARRAY_TASK_ID:?}"
if [[ -f "$MC_REPO/config.env" ]]; then source "$MC_REPO/config.env"; fi
export PYTHONPATH="$MC_REPO/src/molcurator:${PYTHONPATH:-}"
case "$MC_OPERATION" in
 xtb1|orca1) "$MC_PYTHON" "$MC_REPO/src/molcurator/design.py" "${MC_OPERATION%1}" --index "$SLURM_ARRAY_TASK_ID" ;;
 xtb2|orca2) "$MC_PYTHON" "$MC_REPO/src/molcurator/iteration2.py" "${MC_OPERATION%2}" --index "$SLURM_ARRAY_TASK_ID" ;;
 *) echo "Unknown operation $MC_OPERATION" >&2; exit 2 ;;
esac
