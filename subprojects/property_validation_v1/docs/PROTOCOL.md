# Computational protocol and operating checklist

## 1. Define data splits first

Deduplicate canonical isomeric SMILES across all sets. Keep the original 19 test molecules and independent external set out of every training or tuning operation. New candidate selection after inspecting test results is adaptively biased; disclose it. For conformers, split all geometries of the same molecule together.

## 2. 3D preparation and QC

For each SMILES: RDKit AddHs → 30 ETKDGv3 embeddings → MMFF94 minimization (UFF fallback where necessary) → symmetry-aware heavy-atom RMSD clustering at 0.25 Å, selecting up to 5 low-energy representatives → GFN2-xTB optimizations → RMSD reclustering → up to 2 representatives submitted to ORCA 6.1.1, `PBE0/def2-SVP`, `TDA true`, 5 roots, ground-state dipole. ORCA single-point calculations reuse xTB geometries unless expressly stated. xTB orbital energies and ORCA orbital energies are *different methods*, so document the orbitals' method-dependent offsets.

## 3. QC validation

Do not count an output just because a file exists: inspect normal termination, convergence, energy, finite HOMO/LUMO, positive gap, dipole and excited-state roots. `summary.json` and `properties.csv` are the metadata. Retry only failed members; avoid overwriting completed records. The `run400.sbatch` worker checks `status == complete` AND at least one successful ORCA calculation.

## 4. Inference and evaluation

Fingerprints: Morgan radius 2, 1024 bits, followed by xTB HOMO, LUMO, gap, dipole for hybrid models, in this **exact order**. Train only on non-test molecules; evaluate raw xTB, constant delta, linear calibration, xTB RF, hybrid RF, SMILES RF and delta RF on the same targets and molecules. `gap = LUMO - HOMO` must be checked independently for both methods. Dipole is ground-state magnitude in Debye, not a direction-independent vector property.

## 5. Execution order

1. Copy config; run `check` and `demo`.
2. Load preexisting `ml276/ml_dataset.csv`; run `multifidelity`.
3. Run `figures`, then `external` **without fitting on the external set**.
4. `select400`, then `submit400-smoke`, inspect first 2 outputs, then `submit400-rest`.
5. When complete, aggregate via `workflows/qc400/collect400.py`, using arguments from `--help`.
6. Optional design rounds: run each stage and inspect before starting costly QC steps.
7. Save run manifest, tool versions, raw outputs, failures, plot indices and model metadata outside Git, e.g. data archive/DOI.

## 6. Partial automation caveat

Historical workflows have hardcoded old dataset paths and stage-specific assumptions. The unified controller automates repetitive stage execution but requires human gates before expensive SLURM submissions and explicit checks of expected files. It is **not** a LangGraph/Qwen LLM agent or a complete unattended self-driving molecular design system. Planned: conditional acquisition, OOD detection, calibration, automated error recovery, chemical constraint enforcement and genuine new-molecule generation beyond QM9.

## 7. Release checklist

- [ ] Check contributor consent, institutional policy and grant attribution.
- [ ] Check all input datasets' provenance, privacy and licenses.
- [ ] Exclude ORCA executables, HPC credentials and private inputs.
- [ ] Run pytest, `py_compile`, and 2-molecule SLURM smoke test on target environment.
- [ ] Pin environment versions for reproducibility.
- [ ] Confirm external validation path and model loading.
- [ ] Archive huge outputs separately rather than checking into Git.
