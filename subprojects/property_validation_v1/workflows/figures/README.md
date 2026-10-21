# MolCurator presentation figures

Run on an allocated HPC compute node with the `rdkit_env` environment active:

```bash
python -u /home/yo73juc/molcurator/make_presentation_figures.py
```

Default inputs: `/work/AG_Presselt/MolCurator`. Output: `/work/AG_Presselt/MolCurator/presentation_figures_final`.

The script reads actual CSV/JSON files, creates up to 19 PNG figures, skips missing inputs, and writes `FIGURE_INDEX.txt`. It does not launch xTB/ORCA or refit ML. The figure set includes two workflow diagrams (completed vs proposed), QM9 QC distributions, conformer selection and label sensitivity, 94-vs-276 ML performance, external 48-molecule performance, parity/residuals and a copy of the original learning curve.

The newly computed external test should contain **48 valid labeled molecules**, not 50. Check the two missing members separately.

`ml276/model_comparison_94_vs_276.csv` must include model, dataset, mae_ev; `external_test50/external_metrics.csv` must include model, mae_ev; `external_test50/external_predictions.csv` must include s1_ev and combined_rf_pred_ev. No values are invented when a file is absent.

A molecular view PNG gallery requires an actual browser-rendered py3Dmol screenshot. Use the existing `py3dmol_all_html/` / `py3dmol_all_png/` workflow for molecular geometries; this script does not replace these views.
