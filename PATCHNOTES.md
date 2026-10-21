# MolCurator — Patch Notes

## Property Validation and Calibrated Screening
**Date:** 2026-10-21
**Branch:** codex/property-validation-v1
**Status:** Implemented; integration and scientific validation completed

### Added

- Contract-compatible RDKit → GFN2-xTB → ORCA property-validation workflow.
- ETKDGv3 conformer generation, MMFF94 optimization, and UFF fallback.
- Lowest converged force-field energy conformer selection.
- FF-based Boltzmann weight reporting at 298.15 K for the unique sampled conformers.
- xTB-optimized geometry transfer to ORCA.
- Configurable ORCA DFT calculations, including B3LYP/def2-SVP.
- Per-candidate error handling, preserved IDs, and QM attempt recording.
- Calibrated HOMO–LUMO screening and candidate ranking.
- Reproducible calibration and target-enriched validation scripts.
- Consolidated molecular-property validation CSV.
- Automated tests for calibration, ranking, and failure handling.

### Scientific Validation

**Chemistry adapters**
- 26 original automated tests passed.
- Real end-to-end benzene calculation succeeded.
- xTB gap: 4.9343 eV.
- B3LYP/def2-SVP gap: 6.8473 eV.

**Initial calibration**
- 24 successful ORCA calculations.
- 16 calibration molecules and 8 held-out molecules.
- Raw xTB held-out MAE: 2.600 eV.
- Constant-offset held-out MAE: 0.695 eV.
- Linear-calibration held-out MAE: 0.772 eV.

**Target-enriched validation**
- 600 molecules selected for screening.
- 568 successfully screened molecules.
- 60 stratified ORCA validations, all successful.
- Raw xTB validation MAE: 2.231 eV.
- Constant-offset validation MAE: 0.396 eV.
- Linear-calibration validation MAE: 0.364 eV.
- Estimated pool-weighted linear MAE: 0.412 eV.
- One confirmed DFT target hit in the 3.0–3.5 eV window.

### Calibration

Linear correction:

    E_gap(DFT, predicted) = 0.827078 × E_gap(xTB) + 2.990190 eV

Constant-offset correction:

    E_gap(DFT, predicted) = E_gap(xTB) + 2.261744 eV

The calibration targets ORCA B3LYP/def2-SVP orbital gaps
on xTB-optimized geometries.

The raw xTB gap remains unchanged in Prediction.value.
Calibration is applied separately during ranking.

### Current Screening Policy

- Linear calibration is the provisional ranking default.
- A ±0.75 eV margin is available for experimental screening.
- No strict exclusion rule is recommended yet.
- Existing compatible ORCA results should be reused.
- Failed candidates remain present in tool outputs.

### Limitations

- Only one true target hit was identified in the validation set.
- Screening recall is therefore not yet reliably established.
- The 60-molecule validation sample was stratified, not uniformly random.
- The calibration should not be transferred to different DFT methods without validation.
- HOMO–LUMO orbital gaps are not optical excitation energies.
- TADF S1–T1 prediction and validation remain outside this implementation.
- Full calibrated QM-batch selection is not yet integrated into the agent orchestrator.

### Next Steps

1. Connect calibrated candidate ranking to QM-batch selection.
2. Add a cache for previously validated molecular structures and properties.
3. Extend the consolidated dataset to HOMO, LUMO, gap, and dipole descriptors.
4. Test target-directed molecular generation on previously unseen structures.
5. Continue independent validation of screening recall.

### Compatibility

No changes to the existing shared Pydantic tool contracts are required.

The changes are confined to chemistry validation, calibrated screening,
research workflows, tests, and documentation.
