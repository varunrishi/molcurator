# MolCurator — goal-directed QC dataset curation (hackathon reference)

MolCurator explores small neutral C/N/O/F molecular derivatives from a **seed SMILES**, estimates their vertical **S₀→S₁ excitation energies**, selects structures close to a target, and verifies those candidates with ORCA. This repository documents a tested **single-pass** design workflow and a second iteration with QC feedback. It is a research prototype, not a universal molecule generator or a synthesis planner.

## What is included

- `src/molcurator/design.py`: RDKit local graph edits → xTB calculation → saved combined-RF selection → ORCA validation.
- `src/molcurator/iteration2.py`: audit → augment 257 training examples with 8 independently QC-labelled selected structures → updated RF → new proposals → xTB and ORCA QC.
- `legacy/extract_properties.py`: parser for xTB/ORCA outputs.
- `scripts/run_protocol.sh`, `slurm/array_job.sbatch`: automated SLURM array stages with stage-by-stage human review.
- `examples/`: minimal demonstration SMILES plus *reported* numerical results and a figure maker (`scripts/plot_examples.py`). Sample metrics are not training data.
- `tests/`: RDKit smoke tests.

## Quick start: plots without an HPC cluster

```bash
conda env create -f environment.yml
conda activate molcurator
python scripts/plot_examples.py --out figures
pytest -q
```

To try molecule generation on the **illustrative** ethanol seed (no QC/model needed at this stage):

```bash
mkdir -p demo_data/qm9_100
cp examples/seed_demo.csv demo_data/qm9_100/molecules.csv
export MOLCURATOR_DATA_ROOT="$PWD/demo_data"
export MOLCURATOR_SEED_ID=example_ethanol
PYTHONPATH="$PWD/src/molcurator" python src/molcurator/design.py generate --count 10 --min-similarity 0.2
```

Ethanol is only a *software smoke-test input*. It is **not** the scientific `qm9_0023` seed nor is an S₁ target specified for it; no physically validated prediction is produced by this command.

## Run the scientific workflow on SLURM

Requires a local, properly licensed ORCA installation, GFN2-xTB, RDKit Python environment, original `qm9_100/molecules.csv` holding seed `qm9_0023`, `ml276/ml_dataset.csv`, `ml276/combined_rf.joblib` and validated electronic feature extraction. **These data and licensed binaries are not bundled.**

1. `cp config.env.example config.env`; edit real paths, `source config.env`.
2. `bash scripts/run_protocol.sh generate1`
3. `bash scripts/run_protocol.sh submit-xtb1` → verify `squeue --me`, errors and success counts.
4. `bash scripts/run_protocol.sh rank1` → inspect `orca_selected.csv`, novelty and chemistry.
5. `bash scripts/run_protocol.sh submit-orca1` → `bash scripts/run_protocol.sh evaluate1`.
6. `bash scripts/run_protocol.sh audit2` **must pass** before `fit2`.
7. `bash scripts/run_protocol.sh fit2` → `generate2` → `submit-xtb2` → `rank2` → `submit-orca2` → `evaluate2`.

Example controls: `TARGET_S1_EV=4.5 COUNT=200 bash scripts/run_protocol.sh generate1`, `TOP=12 bash scripts/run_protocol.sh rank2`.

SLURM array jobs survive SSH disconnection, unlike an interactive `srun` shell. Check SLURM logs, verify calculation success and prevent duplicate submissions when retrying. Arrays default to `short`, 1 CPU and 2h30; adapt to your site's limits.

## Descriptor contract — important

**Only reuse an RF model with its matching feature pipeline.** The expected vector is 1024 Morgan fingerprint bits (`radius=2`, `fpSize=1024`) followed in this exact order by xTB HOMO, xTB LUMO, xTB gap and xTB dipole: **1028 features**. The first iteration's xTB/ORCA settings should match those used to label the training set. The second-iteration `audit` checks reproducibility of the saved RF predictions and stops on mismatch. This is not a guarantee of molecular applicability: distinguish descriptor range screening from full domain validation.

## Hackathon results (20 Oct 2026)

- Single-geometry labelled dataset: **276** QM9-derived molecules (94 + 182).
- Conformer benchmark: **94** molecules, **2,820** ETKDG structures, **198** FF clusters, **170** xTB clusters, and **133** successful ORCA excited-state calculations. Original-to-selected S₁ shifts >0.05 eV in **17/94**; maximum **0.514 eV**.
- Original frozen 19-molecule holdout, combined RF trained on 257: **MAE 0.4035 eV**, R² **0.7834**.
- Additional 48 QM9 molecules not used in training: **MAE 0.3946 eV**, R² **0.8044**.
- First targeted design (4.50 ± 0.20 eV): **0/8 target hits**, best ORCA S₁ **5.230 eV**, mean signed prediction error **+0.9804 eV**. This highlights surrogate exploitation and the need for feedback.
- Second iteration: 118 xTB-screened candidates, 95 inside training feature min–max ranges, 12 ORCA selected; **QC-validated outcome not included here**.

These outcomes are from one particular QM9-domain dataset/protocol. No claim of experimental photoluminescence, synthesis feasibility or universality to dye-like molecules.

## Scientific limitations

1. The label is gas-phase vertical S₀→S₁ energy from TDA-PBE0/def2-SVP, **not fluorescence wavelength**. Oscillator strength is separate and not an optimization target in the current RF.
2. RDKit sanitization validates molecular graph valences; it does **not** establish chemical stability or synthetic accessibility.
3. Inference requires xTB geometry and descriptors, so the surrogate is cheaper than ORCA but not geometry-free.
4. Model validation on 48 extra QM9 molecules is not external-domain validation; targeted candidate selection is harder than random holdout.
5. Weighting selected conformers by xTB electronic energies is not equivalent to a full free-energy ensemble.
6. New QC-labelled candidates used for `fit2` are *training data* and must never be reported as independent test data for the augmented model.

## Citation / licensing

The code is provided for educational/research reproducibility; RDKit, xTB and ORCA are separate third-party tools with their own licenses. **Check authorship, team approval, cluster rules, and dataset redistribution permissions before making this repository public.** No license is granted to redistribute third-party binaries. Add an appropriate project license and author/collaborator credits before publishing.
