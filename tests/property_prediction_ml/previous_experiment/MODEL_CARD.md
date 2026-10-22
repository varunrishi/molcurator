# Model card

Local model: ExtraTrees regression with 160 trees, leaf size 1 and seed 20261021.
Inputs: chiral Morgan fingerprints radius 2 and 2048 bits, plus 13 structure descriptors.
Target: raw GFN2-xTB HOMO-LUMO orbital gap in eV on a selected converged MMFF94 geometry.
No xTB electronic output is supplied as an input feature. No geometry is needed at inference.

Data: 1000 prospectively sampled unique QM9-like connectivities; 948 usable labels and
52 conformer-generation failures. The 336 earlier molecules were excluded before sampling.
The final random-split model was fitted on 805 development molecules, keeping 143 test
molecules out of fitting and selection. The scaffold-grouped model used 808 development
molecules and 140 held-out molecules, with exact Murcko groups disjoint.

Results for the validation-selected structure-only family
- Random holdout: MAE 0.4069 eV, RMSE 0.5261 eV, R2 0.9329.
- Scaffold holdout: MAE 0.5581 eV, RMSE 0.7827 eV, R2 0.9019.
- Independent earlier cohort of 336: MAE 0.5244 eV, RMSE 0.7650 eV, R2 0.5726.
- Random mean baseline MAE: 1.5921 eV.
- Adding FF features gave MAE 0.3901 eV on random and 0.5677 eV on scaffold holdouts;
  it did not show a consistent benefit and would require FF preparation at inference.

Model selection used validation data, not the test score. Test intervals in the report
are descriptive molecule bootstraps; the grouped split intervals do not correct within-
scaffold dependence. Results are from one seeded partition of each type.

Use the structure_trees.joblib model for the preferred structure-only version.
The fingerprint_ridge.json export is a portable comparison baseline and is less accurate
(random holdout MAE 1.0591 eV); its portability should not be confused with the tree results.

Scope: net-neutral closed-shell connected small molecules; the sampled inputs have 5-9
heavy atoms. Model outputs outside the training size/element range are flagged. Similarity
is a heuristic applicability diagnostic, not calibrated uncertainty. Large conjugated
emitters, net ions, radicals, solvents and TADF were not validated. Learning the xTB teacher
does not establish DFT, excitation-energy or experimental accuracy.

Workflow: generated SMILES -> ML triage -> physical PREDICT for selected molecules ->
validated XYZ -> ORCA VALIDATE if required and budgeted. ML Predictions have no geometry.
They must not be sent directly to ORCA. IDs and failures remain explicit in both the local
CLI and the opt-in shared-contract adapter. Historical note: the study did not modify root training. Current main has an independent training implementation.

Failed geometry cases: 52 geometry-free ML estimates are saved without a reference label;
those values are unvalidated and do not turn the original physical failure into a success.

No Git pull, push or PR action was performed for this local experiment.
