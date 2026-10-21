# MolCurator B3LYP HOMO–LUMO calibration — 24 molecules

Add this folder to an existing checkout at `research/calibration24/`. It **imports the existing team's `molcurator.tools.predict` and `.validate`**, and does not replace any shared contract or chemistry implementation.

Fixed predeclared panel of 24 neutral organic molecules, grouped into 6 chemical families. 16 molecules/4 families are training; 8 molecules/2 unseen families are held out. This is a **small feasibility experiment**, not evidence of robust generalization. Calibration is fitted on training only; test families are never used for calibration. Independently check for overlap with any older MolCurator training dataset before describing the test as novel/prospective.

On login node:

```bash
cd ~/molcurator-property-validation
uv sync
mkdir -p /work/AG_Presselt/MolCurator/calibration24
uv run python research/calibration24/prepare_panel.py --out /work/AG_Presselt/MolCurator/calibration24/panel.csv
```

Smoke test: submit indices 0–1; check successful completion **before** submitting 2–23 (no live QC on login node):

```bash
export REPO="$PWD"
export PANEL=/work/AG_Presselt/MolCurator/calibration24/panel.csv
export OUT=/work/AG_Presselt/MolCurator/calibration24/results
mkdir -p "$OUT"
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=0-1%2 research/calibration24/slurm/one.sbatch
squeue --me
# After the first two jobs have finished, inspect results/ and scheduler output.
sbatch --export=ALL,REPO="$REPO",PANEL="$PANEL",OUT="$OUT" --array=2-23%6 research/calibration24/slurm/one.sbatch
```

Use a different partition if `short` is unavailable. 2 hours and 4 GB are preliminary requests, not guaranteed sufficient. Each successful molecule receives one ORCA B3LYP/def2-SVP evaluation at its xTB-optimized geometry; failed attempts also consume a QC budget. `run_one.py` skips an already successful result, but do not submit duplicate arrays at once.

Collect:

```bash
uv run python research/calibration24/collect.py --manifest "$PANEL" --out "$OUT"
cat "$OUT/metrics.json"
```

Outputs: `all_results.csv`, `test_predictions.csv`, `metrics.json`, per-molecule adapter logs, geometries, conformer metadata. `collect.py` reports raw xTB, train-only mean-offset, and linear fit on untouched test families, including accuracy and potential screening false negatives for a 3.0–3.5 eV target with 0.2 eV margin. If no DFT values lie inside the target window, recall is *undefined* (null), not 100%. 24 small molecules are a method calibration sanity check; for reliable screening safety estimates, more diverse molecules especially near the target threshold will be needed.

The resulting DFT labels are **orbital gaps**, not optical excitation energies. This experiment deliberately does not use prior PBE0 labels for B3LYP calibration.
