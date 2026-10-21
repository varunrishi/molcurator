# MolCurator: existing-data multifidelity benchmark

Runs on the already curated `ml276/ml_dataset.csv` with the **original frozen 19 QM9 molecule IDs**. No new quantum chemistry is performed. Models predict ORCA PBE0/def2-SVP properties measured at xTB-optimized geometries. The HOMO/LUMO gap is not an optical excitation energy.

```bash
conda activate /home/yo73juc/miniforge3/envs/rdkit_env
python -u benchmark.py
```

Override paths with `--data`, `--frozen`, `--out`. Requires NumPy, pandas, scikit-learn, RDKit, matplotlib, joblib. The CSV must contain paired `xtb_{homo_ev,lumo_ev,gap_ev,dipole_debye}` and `orca_{...}` columns, SMILES and molecule_id.

`model_metrics.csv` reports the MAE/RMSE/bias/R2 for each target and approach, `holdout_predictions.csv` allows paired error analyses, `property_audit.csv` gives gap-consistency and delta statistics, and PNG figures show parity, MAE comparisons, and xTB-to-ORCA corrections. Models saved with joblib are for research use only.

**Important:** some conformers/structures can be duplicated under different SMILES; the script excludes canonical-identical test molecules from training, but scaffold splits and stereo/protonation audits should be performed next. If you later benchmark the 48 external molecules, first check matching QC settings, feature representation and the absence of duplicate structures. Never use external test labels for model selection or training in the same reported evaluation.

`linear_calibration` here uses all four xTB descriptors in Ridge regression. `constant_delta` is the simplest single-property xTB correction. The delta RF predicts `(ORCA - xTB)` from Morgan fingerprint plus four xTB descriptors; `hybrid_rf` predicts the ORCA property directly using the same features.
