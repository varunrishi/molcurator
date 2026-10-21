# Molecular property data for collaborators

`molcurator_properties_for_collaborators.csv` shares 336 research records within the team repository. This is a data/documentation contribution, independent of the predictor implementation PRs. All files are inside `subprojects/property_validation_v1/`.

## Included datasets

| dataset | Rows | Reference orbital/property method |
|---|---:|---|
| b3lyp_validation60 | 60 | ORCA B3LYP/def2-SVP |
| historical_pbe0_276 | 276 | Historical ORCA PBE0/def2-SVP |

Keep the datasets separate for method-specific calibration, errors and training targets. The inclusion of both methods in one exchange file does not make their labels interchangeable. Use `(dataset, candidate_id)` as the record identity. Canonical molecular overlap and train/test membership must be checked for each proposed reuse; this sharing check does not establish scaffold novelty or independence between all campaigns.

## Fields and units

- `smiles`, `candidate_id`, `dataset`, `status`, `qm_method`, `reference_method`, `source_csv`: identity and provenance.
- `xtb_*` and `orca_*`: explicit calculated HOMO/LUMO/gap in eV and dipole magnitude in Debye, where available.
- `s1_ev` and `s1_oscillator_strength`: historical vertical excitation energy in eV and dimensionless oscillator strength, where available; S1 is not fluorescence emission.
- `linear_predicted_gap_ev`, `offset_predicted_gap_ev` and error/margin fields: estimates for the B3LYP gap study. Do not apply its frozen correction to PBE0 labels or excitation energies.
- FF fields: force-field method, energy in kcal/mol, sampled-set Boltzmann weight, temperature in K, and unique conformer count. The weight is conditional on sampled FF minima, not an experimental population.
- `selection_probability`, `stratum`: stratified B3LYP sample design metadata. Preserve these when estimating screening-pool metrics; unweighted cohort metrics are not population metrics.

The 60 B3LYP records have status `ok`; the 276 historical PBE0 records have blank status. Do not interpret a blank status as confirmed success or failure. Audit the historical labels and source calculations before reuse.

Blank cells mean unavailable values, never zero. Check `status` and required columns before analysis. Original calculation software, geometry policies and source campaigns may differ; inspect the provenance rather than assuming one common protocol for all 336 rows. Paths in `source_csv` identify original export artifacts and are not necessarily files included by this small data PR.

## Example reuse

```python
import pandas as pd

df = pd.read_csv('subprojects/property_validation_v1/molcurator_properties_for_collaborators.csv')
b3lyp = df[(df.dataset == 'b3lyp_validation60') & (df.status == 'ok')]
pbe0 = df[(df.dataset == 'historical_pbe0_276') & df.orca_gap_ev.notna()]
# PBE0 status is unavailable; a present label alone does not confirm convergence.
# Select reference-method-compatible labels and split by molecular identity
# before fitting or evaluating a model. Keep held-out molecules out of training.
```

The B3LYP cohort contains one observed reference gap in the 3.0–3.5 eV window; this is insufficient to establish reliable screening recall. Data export completeness and software checks do not establish scientific accuracy for a new ML model.

## Source and verification

Copied without changing CSV bytes from `aelm-nv/molcurator`, commit `61f91ec719a5dbe416cada0a9941e578e52ffe6c`, at the same subproject path. The adjacent metadata JSON records the SHA-256 checksum, row counts, method/status counts and units. Verification checked 336 parsed records, the 60/276 split, consistent dataset/method labels, unique composite IDs and uniform CSV shape. No calculations were rerun and raw QC logs were not audited for this sharing operation.

This branch makes the data available for team review. Main changes only when this pull request is reviewed and merged.
