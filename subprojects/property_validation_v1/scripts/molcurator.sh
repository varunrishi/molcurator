#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$REPO/config.env" ]] && source "$REPO/config.env"
MC_ROOT="${MC_ROOT:-/work/AG_Presselt/MolCurator}"
MC_PYTHON="${MC_PYTHON:-python}"
MC_SOURCE="${MC_SOURCE:-/home/yo73juc/molcurator/QM9_smiles.txt}"
MC_PARTITION="${MC_PARTITION:-short}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
usage(){ cat <<'HELP'
Usage: bash scripts/molcurator.sh COMMAND
  check                Check environment, model/data paths
  demo                 Plot included example observations (no xTB/ORCA)
  status400            Count completed records of 400-batch
  select400            Select 400 unseen molecules (irreversible manifest; no overwrite)
  submit400-smoke      Submit first 2 molecules to SLURM
  submit400-rest       Submit molecule indices 2..399 to SLURM
  collect400           Aggregate QC labels and statuses
  train276             Train S1 surrogate, preserving original frozen holdout
  multifidelity        Benchmark HOMO/LUMO/gap/dipole, no QC jobs
  figures              Make multifidelity figures from existing holdout
  external             Score frozen multifidelity models on external QC set
  allfigures           Make full presentation figure library
  design1-CMD          generate / rank / evaluate
  design2-CMD          audit / fit / generate / rank / evaluate
  design1-xtb          Submit design iteration 1 xTB jobs
  design1-orca         Submit design iteration 1 ORCA jobs
  design2-xtb          Submit design iteration 2 xTB jobs
  design2-orca         Submit design iteration 2 ORCA jobs
  test                 Run local smoke tests
QC submissions require MC_ALLOW_SUBMIT=true (run check/smoke first).
HELP
}
run(){ "$MC_PYTHON" -u "$@"; }
submit(){
 [[ "${MC_ALLOW_SUBMIT:-false}" == true ]] || { echo 'Blocked QC submission; set MC_ALLOW_SUBMIT=true in config.env after reviewing cluster limits.' >&2;exit 2; }
 sbatch "$@"
}
verify(){ [[ -f "$1" ]] || { echo "Missing required file: $1" >&2;exit 3; }; }
count_rows(){ "$MC_PYTHON" - "$1" <<'PYCOUNT'
import csv,sys
with open(sys.argv[1],newline='') as f: print(sum(1 for _ in csv.DictReader(f)))
PYCOUNT
}
array_for(){ local file="$1" limit="$2" job="$3"; verify "$file";local n; n="$(count_rows "$file")";((n>0)) || exit 3;submit --partition="$MC_PARTITION" --array="0-$((n-1))%${limit}" "$job"; }
case "${1:-}" in
 check) run "$REPO/scripts/preflight.py" --root "$MC_ROOT" --source "$MC_SOURCE" ;;
 demo) run "$REPO/scripts/demo.py" --out "$REPO/examples/generated_figures" ;;
 select400) run "$REPO/workflows/qc400/select_400.py" --source "$MC_SOURCE" --root "$MC_ROOT" --count 400 ;;
 submit400-smoke) verify "$MC_ROOT/qm9_400/molecules.csv";submit --partition="$MC_PARTITION" --export=ALL,ROOT="$MC_ROOT/qm9_400",PYTHON="$MC_PYTHON" --array="0-1%2" "$REPO/workflows/qc400/slurm/run400.sbatch" ;;
 submit400-rest) verify "$MC_ROOT/qm9_400/molecules.csv";n="$(count_rows "$MC_ROOT/qm9_400/molecules.csv")"; ((n>2)) || { echo 'No remaining jobs';exit 2;};submit --partition="$MC_PARTITION" --export=ALL,ROOT="$MC_ROOT/qm9_400",PYTHON="$MC_PYTHON" --array="2-$((n-1))%${MC_XTB_MAX_ACTIVE:-8}" "$REPO/workflows/qc400/slurm/run400.sbatch" ;;
 status400) run "$REPO/scripts/status400.py" --root "$MC_ROOT/qm9_400" ;;
 collect400) run "$REPO/workflows/qc400/collect400.py" --root "$MC_ROOT/qm9_400" ;;
 train276) run "$REPO/workflows/ml276/train_expanded.py" ;;
 multifidelity) run "$REPO/workflows/multifidelity/benchmark.py" ;;
 figures) run "$REPO/workflows/multifidelity_next/benchmark_next.py" plots --benchmark "$MC_ROOT/multifidelity_benchmark" --training "$MC_ROOT/ml276/ml_dataset.csv" --out "$MC_ROOT/multifidelity_next" ;;
 external) run "$REPO/workflows/multifidelity_next/benchmark_next.py" external --benchmark "$MC_ROOT/multifidelity_benchmark" --external "$MC_ROOT/external_test50" --training "$MC_ROOT/ml276/ml_dataset.csv" --out "$MC_ROOT/multifidelity_next" ;;
 allfigures) run "$REPO/workflows/figures/make_presentation_figures.py" ;;
 design1-generate|design1-rank|design1-evaluate) sub="${1#design1-}";shift;run "$REPO/workflows/design/design.py" "$sub" "$@" ;;
 design2-audit|design2-fit|design2-generate|design2-rank|design2-evaluate) sub="${1#design2-}";shift;run "$REPO/workflows/iteration2/iteration2.py" "$sub" "$@" ;;
 design1-xtb|design1-orca|design2-xtb|design2-orca)
  case "$1" in
   design1-xtb) file="$MC_ROOT/design_qm9_0023/molecules.csv";job="$REPO/workflows/design/xtb_array.sbatch";lim="${MC_XTB_MAX_ACTIVE:-8}";;
   design1-orca) file="$MC_ROOT/design_qm9_0023/orca_selected.csv";job="$REPO/workflows/design/orca_array.sbatch";lim="${MC_ORCA_MAX_ACTIVE:-4}";;
   design2-xtb) file="$MC_ROOT/design_iteration2/molecules.csv";job="$REPO/workflows/iteration2/xtb_iter2.sbatch";lim="${MC_XTB_MAX_ACTIVE:-8}";;
   design2-orca) file="$MC_ROOT/design_iteration2/orca_selected.csv";job="$REPO/workflows/iteration2/orca_iter2.sbatch";lim="${MC_ORCA_MAX_ACTIVE:-4}";;
  esac
  array_for "$file" "$lim" "$job" ;;
 test) "$MC_PYTHON" -m pytest -q "$REPO/tests" ;;
 *) usage;exit 2;;
esac
