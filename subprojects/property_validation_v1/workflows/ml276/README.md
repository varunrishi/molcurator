# MolCurator expanded ML benchmark (94 → 276 molecules)

Requires: Python 3.10, pandas, NumPy, RDKit, scikit-learn, matplotlib, joblib.

Uses the **same 19 molecule IDs** from `qm9_100/baseline94/frozen_test_ids.csv`.
Collects `qm9_100/*/properties.csv` and `qm9_200/*/properties.csv`, checks quality, canonicalizes SMILES, drops duplicates, excludes the frozen 19 from training, and evaluates five models.

Run on an allocated node:

```bash
conda activate /home/yo73juc/miniforge3/envs/rdkit_env
python -u /home/yo73juc/molcurator/molcurator_ml276/train_expanded.py
```

Default output is `/work/AG_Presselt/MolCurator/ml276`.
Important outputs: `model_comparison_94_vs_276.csv`, `mae_comparison_94_vs_276.png`, `predicted_vs_qc_276.png`, `learning_curve.png`, `holdout_predictions_276.csv`, `ml_dataset.csv` and trained `*.joblib` models.

If the validated set contains slightly fewer than 276 unique structures, the script reports the actual size. A model with xTB descriptors requires computing xTB features before inference on a generated molecule. Do not use original held-out labels for model selection or tuning. A separate scaffold split is a future validation step.
