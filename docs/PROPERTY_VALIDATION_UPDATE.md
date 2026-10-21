# MolCurator — Property validation and calibrated screening update

**Shared update branch:** `codex/calibrated-screening-v1` (based on `codex/property-validation-v1`)
**Scope:** Chemistry/property-validation contributor; additive integration with v0.1-contract.

## Implementation status

- The contract-compatible `predict()` tool implements ETKDG conformer search, MMFF94/UFF force-field optimization, deduplication at 0.25 Å RMSD, and selection of the lowest converged FF-energy conformer. Its sampled FF-based Boltzmann weight at 298.15 K is written to a geometry report. It then performs one GFN2-xTB optimization and returns the raw xTB orbital gap and optimized XYZ.
- The `validate()` tool performs one ORCA single-point calculation per selected successful prediction, using the supplied `QMSettings` (B3LYP/def2-SVP in the HOMO–LUMO config); it preserves IDs, statuses and errors and records QM attempts including failures.
- Earlier cluster check: **26/26 passed**; the current combined offline suite has **42/42 passed** locally. Real benzene smoke test succeeded: **4.93426034 eV** xTB gap and **6.84730000 eV** ORCA B3LYP/def2-SVP gap.
- Calibration campaign: **24/24 successful** (16 calibration, 8 held-out). On the 8-molecule holdout MAEs were 2.600 eV (raw), 0.695 eV (constant offset), 0.772 eV (linear).
- Target-enriched experiment: **568** successful xTB-screened molecules, **60/60** selected ORCA validations succeeded, **one** DFT hit in the 3.0–3.5 eV window. On the 60 validation molecules MAEs: raw 2.231 eV, constant offset 0.396 eV, linear 0.364 eV. Inverse-probability-weighted pool MAEs: raw 2.047 eV, constant offset 0.545 eV, linear 0.412 eV (sampling uncertainty not quantified).

## Frozen calibration and provisional use

Fit on the original **16-molecule calibration split**, not refit on target-enriched labels:

- `linear_24`: `gap_DFT_pred = 0.8270780546046135 * gap_xTB + 2.9901896256531098 eV`.
- `constant_offset_24`: `gap_DFT_pred = gap_xTB + 2.2617441034023127 eV`.
- Intended domain: GFN2-xTB → ORCA B3LYP/def2-SVP HOMO–LUMO *orbital* gap; neutral, closed-shell molecular cases on xTB-optimized geometry. Not S1 excitations, emission or S1–T1.
- Recommend **provisional linear-calibrated ranking**, with 0.75 eV *exploratory selection band*, plus candidates outside the band; **do not apply as a hard exclusion rule**. One observed DFT target hit was recovered by linear calibration at margins ≥0.5 eV, but missed at 0.2 eV. One success does **not** establish population recall or justify a safe rejection bound. The enriched sample and inverse-probability weighting must be distinguished when reporting estimates.
- Keep raw `Prediction.value` unchanged; call `molcurator.screening.ranked_predictions(...)` after `predict()` and before choosing a QM batch. The orchestration layer owns QM budgets. This patch does **not** enable automatic screening in the unfinished agent graph.

## Scientific and implementation limitations

1. Current FF conformer Boltzmann weight is conditional on the sampled and deduplicated FF minima and is not a full thermodynamic population.
2. Calibration is method-specific; do not apply unchanged to earlier PBE0/def2-SVP datasets.
3. Only one true 3.0–3.5 eV hit among 60 validated molecules. Screening sensitivity remains uncertain; continue independent probability-sampled validation and preserve selection probabilities.
4. Errors for unsupported chemistry (charged/open-shell species) remain explicit. TADF is out of scope and requires singlet/triplet protocols.
5. All 60 ORCA calls were part of a separate scientific evaluation; they must **not** be presented as an agent run within the standard 20-QM-call budget.
6. The proposed model ranking is a research utility, not a deployed orchestrator policy. Request collaborator review before changing `screening.margin` defaults.

## Files in the patch

- `src/molcurator/screening/gap.py`: calibration and stable-ranked predictions, while preserving original IDs and failures.
- `scripts/rank_calibrated_predictions.py`: export ranked screening results from JSON to CSV.
- `tests/test_calibrated_screening.py`: offline contract-invariance and edge-case tests.
- `research/property_validation_results/calibration_summary.json`: checked-in coefficients and reported summary results (not a replacement for raw datasets).

## Next steps

1. Run the full test suite, review additive diff, and push this branch.
2. Load existing prediction JSON through the ranking utility, independently from QM tools.
3. Agree with orchestrator maintainer on a ranking-plus-exploration rule; retain nonzero exploration budget.
4. Gather further independent target-hit validations and uncertainty intervals before adopting any hard screening bound.
5. Export per-molecule full xTB/ORCA properties and provenance separately for GitHub; do not commit large proprietary QC logs or trained binaries.
