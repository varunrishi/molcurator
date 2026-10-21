# MolCurator — automated molecular curation and multifidelity screening

**Research prototype, 20 October 2026.** Python + RDKit / MMFF94 / xTB / ORCA / scikit-learn, with SLURM automation. This repository consolidates the actual scripts used in the hackathon. It does **not** include ORCA, xTB executables, the large QC dataset, pretrained models, or credential files. ORCA use is subject to its license and local HPC policies.

## What is implemented

- **Conformer-aware QC**: ETKDGv3 3D generation, MMFF94 (UFF fallback), RMSD clustering, GFN2-xTB refinement and reclustering, PBE0/def2-SVP ORCA TDA and ground-state property extraction.
- **Dataset expansion**: select 400 unseen QM9 molecules, checkpointed SLURM job arrays, collection.
- **S1 ML**: 94 vs 276 training workflow, original 19-member frozen test, and an external QM9 test.
- **Multifidelity models**: raw xTB, constant correction, linear calibration, SMILES-only RF, xTB RF, hybrid RF and RF Δ-learning for HOMO/LUMO/gap/dipole.
- **Inverse design demo**: seed graph edits → xTB → ML ranking → ORCA checks → iteration 2 correction.
- **Plots**: study figures, parity plots, error analysis, model comparisons and included no-QC demonstration.

## Quick start on a SLURM cluster

```bash
unzip MolCurator_Automated_GitHub.zip
cd MolCurator_Automated_GitHub
cp config.env.example config.env
nano config.env  # adapt paths; DO NOT commit this file
conda env create -f environment.yml   # or reuse existing rdkit_env
bash scripts/molcurator.sh check
bash scripts/molcurator.sh demo
bash scripts/molcurator.sh test
```

The workflows' historical Python scripts use hard-coded paths in some places; **they are preserved as research provenance**. For reproduction on another cluster, update their path defaults as described in `docs/PROTOCOL.md`. Commands `figures`, `multifidelity`, and `train276` assume the prior data layout. This package provides single-command stage automation with checkpointing, **not an unattended universal agent**, and it is important to review QC selection before submission.

### 400 fresh molecules

```bash
bash scripts/molcurator.sh select400
bash scripts/molcurator.sh status400
# after validation, change MC_ALLOW_SUBMIT=true in config.env:
bash scripts/molcurator.sh submit400-smoke
bash scripts/molcurator.sh status400
bash scripts/molcurator.sh submit400-rest
```

### Multifidelity benchmark and figures

```bash
bash scripts/molcurator.sh multifidelity
bash scripts/molcurator.sh figures
bash scripts/molcurator.sh external
bash scripts/molcurator.sh allfigures
```

If models are saved in `<MC_ROOT>/multifidelity_benchmark`, the consolidated external validator checks that directory directly. The earlier incorrect `validate_external` argument call has been corrected.

### Design demonstration

```bash
bash scripts/molcurator.sh design1-generate --count 200 --target 4.5
bash scripts/molcurator.sh design1-xtb
# wait and check outcomes
bash scripts/molcurator.sh design1-rank --target 4.5 --top 8
bash scripts/molcurator.sh design1-orca
bash scripts/molcurator.sh design1-evaluate --target 4.5
bash scripts/molcurator.sh design2-audit
bash scripts/molcurator.sh design2-fit
bash scripts/molcurator.sh design2-generate --count 300 --target 4.5
bash scripts/molcurator.sh design2-xtb
bash scripts/molcurator.sh design2-rank --target 4.5 --top 12
bash scripts/molcurator.sh design2-orca
bash scripts/molcurator.sh design2-evaluate --target 4.5
```

## Reproduced / reported project results (not recalculated here)

- 276 single-geometry molecules with QC data (257 original training / 19 frozen test).
- 94 conformer-aware molecules: 2,820 initial conformers; 198 force-field clusters; 170 xTB clusters; 133 ORCA evaluations.
- S1 combined RF: original 19 MAE 0.4035 eV; 48 independent held-out QM9 MAE 0.3946 eV.
- HOMO/LUMO/dipole ΔRF MAE 0.187 eV / 0.199 eV / 0.210 D (original 19); gap constant-delta MAE 0.308 eV.
- First inverse-design cycle: 8 ORCA validations, zero within 4.5±0.2 eV; mean error 0.9804 eV. Iteration 2 had 12 selected, outcomes **not supplied/verified**.

These are method-specific quantum-chemical targets, not experimental observables. Do not describe vertical S1 excitation as fluorescence emission, or a DFT Kohn–Sham gap as the optical gap. Conformers and chemistry must be split at molecular level to prevent leakage; xTB and ORCA orbitals can have large different method-dependent offsets.

## Repository map

- `workflows/qc400` — 400-molecule selection, conformer pipeline and SLURM
- `workflows/conformers` — original conformer-processing implementation
- `workflows/ml276` — S1 training
- `workflows/external` — external QM9 test pipeline
- `workflows/multifidelity` — property benchmark
- `workflows/multifidelity_next` — plots and external validation
- `workflows/design`, `workflows/iteration2` — inverse design rounds
- `workflows/figures` — consolidated plots
- `scripts/molcurator.sh` — unified CLI + submission safeguards
- `examples` — lightweight sample data and offline plot demo
- `archive_previous` — earlier repository draft retained for provenance
- `docs/PROTOCOL.md` — method documentation, reproducibility and known limitations

## Citation, license and release

Identify all collaborators and institutional affiliations and choose a compatible license **before public release**. The source scripts and reported values were produced in a rapid hackathon; validate parser details, convergence and SCF results before scientific reuse. A copyright/license grant is not implied by the ZIP.
