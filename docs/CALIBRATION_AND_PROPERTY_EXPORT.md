# Calibration and property export update — 2026-10-21

## Scientific results

24 ORCA B3LYP/def2-SVP calculations (16 fit, 8 held out) and 60 further target-enriched validations succeeded. The independent 60-molecule sample produced MAE of 2.231 eV (raw GFN2-xTB), 0.396 eV (constant-offset corrected), and 0.364 eV (linear corrected). Inverse-probability weighted MAEs estimated for the 568 successfully screened QM9 molecules were 2.047, 0.545 and 0.412 eV, respectively. Only one validated molecule was within the 3.0–3.5 eV DFT gap window; **no defensible true-hit recall has been established**. Sampling weights account for the stratified design but not uncertainty from the small number of observed hits.

Frozen 16-molecule calibrations:

- Linear: `E_DFT_pred = 0.8270780546 * E_xTB + 2.9901896257 eV`.
- Constant: `E_DFT_pred = E_xTB + 2.2617441034 eV`.

## Agent integration

`Prediction.value` remains raw GFN2-xTB gap; `QMResult.value` remains reference ORCA B3LYP/def2-SVP gap. Calibration is **post-processing** for ranking and provisional prioritization, not a hard reject mechanism. The existing tools/schemas need no modifications. Exported calculated reference values are not replaced by calibration predictions.

## Property-export fields and provenance

`export_calibrated_properties.py` reads `target_validation/screen/validation_results.csv`, preserving status, errors, candidate ID, SMILES, xyz path, selection strata and inverse probability weights, and produces one row per validation attempt. It computes both calibrated predictions and signed errors; creates a metadata JSON. Optional FF geometry metadata can be loaded from reports. Unavailable frontier orbital energies/dipoles stay blank and are **not inferred** from orbital gaps. When `--historical` is given, an **independent** CSV is created with properties from the earlier PBE0/def2-SVP 276-molecule dataset; never join these distinct QM methods as if they shared a target.

QC geometry policy: lowest converged sampled FF conformer, reporting FF-based Boltzmann weight at 298.15 K among unique sampled conformers; GFN2-xTB geometry optimization followed by one ORCA DFT single-point calculation. This is not DFT geometry optimization.

## Command

```bash
uv run --with pandas python scripts/export_calibrated_properties.py \
  --validation /work/AG_Presselt/MolCurator/target_validation/screen/validation_results.csv \
  --output research/property_validation_results/calibrated_properties.csv \
  --historical /work/AG_Presselt/MolCurator/ml276/ml_dataset.csv
```

The 60 B3LYP validation CSV and 276 PBE0 historical CSV are two distinct datasets.
