# Target-enriched prospective screening validation

Unmodified team adapters; **600 unused QM9** structures are sampled, RDKit+GFN2-xTB screened, then **60 ORCA B3LYP/def2-SVP** validations selected by randomized stratified sampling. Frozen correction: `xTB_gap + 2.2617441034023127 eV` from the previous 16 training structures. Also assess raw xTB and the previously fitted linear model. Target DFT gap: **3.0–3.5 eV**.

## Run on HPC (from team repository root)

```bash
cd ~/molcurator-property-validation
unzip /path/to/molcurator_target_validation.zip
mkdir -p research
mv molcurator_target_validation research/target_validation
export REPO=$PWD
export ROOT=/work/AG_Presselt/MolCurator/target_validation
mkdir -p "$ROOT"
export PANEL="$ROOT/pool.csv"
export OUT="$ROOT/screen"
uv run python research/target_validation/prepare_pool.py --output "$PANEL" --n 600
# Only after verifying appropriate SLURM partition, quota, and competing 500 jobs:
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=0-1%2 research/target_validation/slurm/screen.sbatch
# After two succeed:
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=2-599%12 research/target_validation/slurm/screen.sbatch
# After all screening jobs finish:
uv run python research/target_validation/collect_screen.py --manifest "$PANEL" --out "$OUT"
uv run python research/target_validation/choose_validation.py --screened "$OUT/screened.csv" --output "$ROOT/validate_panel.csv" --n 60
export PANEL="$ROOT/validate_panel.csv"
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=0-1%2 research/target_validation/slurm/validate.sbatch
# After two succeed:
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=2-59%6 research/target_validation/slurm/validate.sbatch
# After ORCA jobs finish:
uv run python research/target_validation/analyze.py --manifest "$PANEL" --out "$OUT"
```

The **600 xTB calls and 60 ORCA calls are a separate scientific calibration campaign**, *not* within the agent's configured 20-QM-call budget. Obtain project quota approval. SLURM concurrency `%12` / `%6` can be reduced. Jobs survive SSH logout. `screened.csv`, `validate_panel.csv`, `validation_results.csv` and `screening_metrics.json` are the research deliverables. Do not rerun successful jobs or submit overlapping arrays.

## Statistics and limitations

- Every successfully screened molecule is assigned to exactly one stratum by its **frozen** corrected xTB distance from [3.0,3.5] eV. Sampled candidates are randomly chosen *within* each nonempty stratum, and all selected records retain their inclusion probability (`stratum_selected / stratum_population`). Thus inverse-probability weights permit estimation of screening *pool-level* metrics for the **successfully screened** 600-molecule pool, as long as the ORCA sample has complete labels and all represented strata have nonzero sample size.
- The sample is **target enriched**: unweighted MAE and recall describe the enriched sample, **not the screening pool**. Weighted metrics are estimated pool metrics, subject to potentially large uncertainty; n=60 may be inadequate for reliable recall.
- Explicit failures from the xTB screen are retained but excluded from weighted pool estimation. We make no claims about their true DFT hits.
- `n_true_hits=0` gives `recall: null`, **not** zero false-negative risk. If no hit is found, consider enlarging the pool and revisiting the chemistry space, target and screening policy.
- Boltzmann weights are sampled FF-model-dependent. All methods are orbital HOMO–LUMO gaps, not excitation energies. Existing PBE0 models must not be presented as B3LYP-calibrated.
- The adapter's `validate` writes ORCA `attempt.json` in the screening folder. **Failed ORCA attempts count toward QM usage**. Do not casually rerun failures; confirm the remaining computational budget and attempt logs first.
- **Check molecule IDs/SMILES** against any external held-out benchmarks before final publication; the selector handles the common historical manifests, not undocumented datasets.
