# MolCurator 400-new-molecule conformer-aware QC batch

This is an extension of the *same* pipeline used for the completed 94-molecule conformer experiment. Neutral closed-shell QM9 molecules only. Source is the existing `/home/yo73juc/molcurator/QM9_smiles.txt`.

## Pipeline

1. Select 400 unique structures (canonical isomeric SMILES), removing molecules from prior QM9 batches, external test, both generated design pools and a pre-existing qm9_400 batch.
2. Per molecule: 30 RDKit ETKDGv3 embeddings → **MMFF94** minimization (UFF fallback if MMFF parameters unavailable) → energy-window and heavy-atom RMSD cluster (0.25 Å) → up to 5 FF representatives.
3. GFN2-xTB geometry optimization, within 5 kcal/mol and post-xTB RMSD clustering (0.25 Å).
4. PBE0/def2-SVP ORCA ground-state calculation with TDA roots on up to 2 selected xTB optimized geometries. ORCA HOMO/LUMO and **ground-state dipole** are parsed from the same output. Note ORCA calculations are **single points at xTB geometries**, not ORCA geometry optimizations.
5. Status and per-conformer files; one lowest-xTB representative per molecule for straightforward ML while preserving all valid conformer labels separately.

## Setup / submit (on HPC login node)

```bash
unzip molcurator_400.zip -d /home/yo73juc/molcurator/
cd /home/yo73juc/molcurator/molcurator_400
/home/yo73juc/miniforge3/envs/rdkit_env/bin/python select_400.py
# Verify selector: should print 400
head /work/AG_Presselt/MolCurator/qm9_400/molecules.csv
# Smoke test on 2 structures
sbatch --export=ALL,ROOT=/work/AG_Presselt/MolCurator/qm9_400 --array=0-1%2 slurm/run400.sbatch
squeue --me
# Inspect both summary.json files. If all fine, submit remainder:
sbatch --export=ALL,ROOT=/work/AG_Presselt/MolCurator/qm9_400 --array=2-399%8 slurm/run400.sbatch
```

The %8 cap is illustrative: adjust to the cluster's fair-use limits. `short` 3h is for small QM9 molecules; inspect failures and request more time if necessary. Do not run production QC on a login node.

### Status / aggregation

```bash
python collect400.py
find /work/AG_Presselt/MolCurator/qm9_400/conformer_runs -name summary.json | wc -l
```

Output: `workflow_status.csv`, `all_valid_conformers.csv`, `representative_labels.csv` in `qm9_400/`. **Do not merge into the frozen test sets or retrain without making a separate experiment.** Keep a molecular-ID split to avoid conformer leakage.

### Restart

Rerunning the array safely skips molecules marked `complete`. Incomplete jobs rerun their molecule folder. The underlying pipeline is not checkpointed within a molecule: if the time limit kills a job mid-calculation, re-running may repeat some QC work.

### Limits

Sampling/clustering is heuristic; FF energies and xTB electronic energies are not conformational free energies. Error control uses normal ORCA termination and parsed S1; verify available HOMO/LUMO/dipole columns before using a property for ML. No synthetic stability verification. QC method: GFN2-xTB / ORCA PBE0 def2-SVP, TDA 5 roots. No full ORCA geometry relaxation.
