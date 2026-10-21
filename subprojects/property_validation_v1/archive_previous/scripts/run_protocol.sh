#!/usr/bin/env bash
# Usage: bash scripts/run_protocol.sh {generate1|submit-xtb1|rank1|submit-orca1|evaluate1|audit2|fit2|generate2|submit-xtb2|rank2|submit-orca2|evaluate2}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/config.env" ]]; then source "$ROOT/config.env"; fi
: "${MOLCURATOR_DATA_ROOT:?Set MOLCURATOR_DATA_ROOT in config.env}"
PYTHON="${MOLCURATOR_PYTHON:-python}"
export PYTHONPATH="$ROOT/src/molcurator:${PYTHONPATH:-}"
D1="$ROOT/src/molcurator/design.py";D2="$ROOT/src/molcurator/iteration2.py"
X1="${MOLCURATOR_DESIGN1_DIR:-$MOLCURATOR_DATA_ROOT/design_qm9_0023}"
X2="${MOLCURATOR_DESIGN2_DIR:-$MOLCURATOR_DATA_ROOT/design_iteration2}"
TARGET="${TARGET_S1_EV:-4.5}"
count_csv() { "$PYTHON" - "$1" <<'PY'
import csv,sys
with open(sys.argv[1],newline='') as f: print(sum(1 for _ in csv.DictReader(f)))
PY
}
submit_array() {
  local csv="$1" op="$2" folder="$3" script="$4" max="$5"
  [[ -f "$csv" ]] || { echo "Missing $csv" >&2; exit 2; }
  local n; n="$(count_csv "$csv")"
  ((n>0)) || { echo 'No rows to submit' >&2;exit 2; }
  mkdir -p "$folder/logs"
  sbatch --partition="${MOLCURATOR_PARTITION:-short}" --array="0-$((n-1))%${max}" \
    --output="$folder/logs/${op}_%A_%a.log" --export=ALL,MC_REPO="$ROOT",MC_OPERATION="$op",MC_PYTHON="$PYTHON" "$ROOT/slurm/array_job.sbatch"
}
case "${1:-}" in
 generate1) "$PYTHON" "$D1" generate --count "${COUNT:-200}" --target "$TARGET" ;;
 submit-xtb1) submit_array "$X1/molecules.csv" xtb1 "$X1" "$D1" 8 ;;
 rank1) "$PYTHON" "$D1" rank --top "${TOP:-8}" --target "$TARGET" ;;
 submit-orca1) submit_array "$X1/orca_selected.csv" orca1 "$X1" "$D1" 4 ;;
 evaluate1) "$PYTHON" "$D1" evaluate --target "$TARGET" ;;
 audit2) "$PYTHON" "$D2" audit ;;
 fit2) "$PYTHON" "$D2" fit ;;
 generate2) "$PYTHON" "$D2" generate --count "${COUNT:-300}" --target "$TARGET" ;;
 submit-xtb2) submit_array "$X2/molecules.csv" xtb2 "$X2" "$D2" 8 ;;
 rank2) "$PYTHON" "$D2" rank --top "${TOP:-12}" --target "$TARGET" ;;
 submit-orca2) submit_array "$X2/orca_selected.csv" orca2 "$X2" "$D2" 4 ;;
 evaluate2) "$PYTHON" "$D2" evaluate --target "$TARGET" ;;
 *) echo 'Usage: bash scripts/run_protocol.sh {generate1|submit-xtb1|rank1|submit-orca1|evaluate1|audit2|fit2|generate2|submit-xtb2|rank2|submit-orca2|evaluate2}' >&2;exit 2 ;;
esac
