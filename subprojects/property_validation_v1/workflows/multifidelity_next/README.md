# MolCurator: multifidelity figures + independent external validation

The analysis uses the **previously trained** multifidelity models in `multifidelity_benchmark/`, the saved frozen 19-molecule predictions, and the 48 valid independent QM9 property records in `external_test50/test_*/properties.csv`. It does not train or overwrite a model.

## Setup

```bash
conda activate /home/yo73juc/miniforge3/envs/rdkit_env
python -u benchmark_next.py plots
python -u benchmark_next.py external
```

Optionally customize paths with `--benchmark`, `--external`, `--training`, `--frozen`, `--out`. Defaults follow the Leibniz-IPHT cluster layout from the project.

## Artifacts

- `multifidelity_next/original19/`: model MAE (all strategies, for each property); xTB-vs-ORCA scatter, correction histogram, residual and parity plots; checked metrics; publication-ready PNG (300 dpi) and vector PDF.
- `multifidelity_next/external48/`: analogous figures, `external_property_predictions.csv`, `external_coverage.csv`, validated metrics. Actual N can be fewer than 48 when paired property fields are missing.

## Reproducibility and scientific caveats

- Exclude external molecules that duplicate **any** original 276 molecules via canonical isomeric SMILES.
- External evaluation reuses saved `.joblib` models without refitting. The constant correction is recovered exclusively from nonfrozen training molecules.
- Fingerprints are Morgan radius 2 / 1024 bits with the same ordering as training, then xTB `[HOMO, LUMO, gap, dipole]` for hybrid/Delta models.
- Both electronic-structure methods must use consistent geometries; original ORCA calculations were single-points on xTB-optimized geometries.
- HOMO/LUMO are model-dependent Kohn-Sham/tight-binding orbital eigenvalues, not measured ionization potentials or electron affinities.
- The 48 external molecules are out-of-training QM9 samples, not a new chemistry domain.
- Avoid claiming 19-point model rankings statistically significant without uncertainty quantification. Avoid tuning on the external evaluation set.
