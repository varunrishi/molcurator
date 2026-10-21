#!/bin/bash
#SBATCH --job-name=mc400
#SBATCH --partition=short
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=5G
#SBATCH --output=mc400-%A_%a.log
set -euo pipefail
ROOT=${ROOT:-/work/AG_Presselt/MolCurator/qm9_400}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=${PYTHON:-/home/yo73juc/miniforge3/envs/rdkit_env/bin/python}
export XTB_BIN=${XTB_BIN:-/vast/yo73juc/miniconda3/envs/cresta/bin/xtb}
export ORCA_BIN=${ORCA_BIN:-/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
# Read records by CSV module, not shell IFS; robust against additional columns.
readarray -t ENTRY < <("$PYTHON" - "$ROOT/molecules.csv" "$SLURM_ARRAY_TASK_ID" <<'PY'
import csv,sys
with open(sys.argv[1],newline='') as f:
    data=list(csv.DictReader(f))
i=int(sys.argv[2]);assert 0<=i<len(data)
print(data[i]['molecule_id']);print(data[i]['smiles'])
PY
)
MID=${ENTRY[0]}; SMILES=${ENTRY[1]}
OUT="$ROOT/conformer_runs/$MID"
if [[ -f "$OUT/summary.json" ]] && "$PYTHON" - "$OUT/summary.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]));sys.exit(0 if p.get('status')=='complete' and p.get('n_orca_success',0)>0 else 1)
PY
then
 echo "Already completed $MID; skipping";exit 0
fi
"$PYTHON" "$HERE/molcurator_conformers/conformer_pipeline.py" \
 --id "$MID" --smiles "$SMILES" --out "$OUT" \
 --nconfs 30 --ff-rms 0.25 --ff-window 5.0 \
 --max-xtb 5 --xtb-rms 0.25 --xtb-window 5.0 \
 --max-orca 2 --nroots 5
