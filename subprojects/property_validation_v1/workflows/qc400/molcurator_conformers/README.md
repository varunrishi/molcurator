# MolCurator conformer-aware QC workflow

Requires RDKit Python, xTB 6.7.1, ORCA 6.1.1. `extract_properties.py` is the existing parser and must live next to `conformer_pipeline.py`.

The workflow runs ETKDGv3, MMFF94 (UFF fallback) with convergence checks, greedy lowest-energy-first symmetry-aware heavy-atom RMSD clustering, selects up to five unique FF conformers (within 5 kcal/mol), optimizes with GFN2-xTB, clusters again on optimized geometry (within 5 kcal/mol), and submits up to two conformers to ORCA TDA-PBE0/def2-SVP. It writes `summary.json`, `conformer_properties.csv`, and one folder per xTB conformer with geometries and logs. The energies and optical states are geometry-specific, **not ensemble-averaged**. ORCA is a single point at the GFN2-xTB geometry; this is not an optimized excited-state fluorescence calculation.

## Install to user's cluster

Copy `conformer_pipeline.py`, `extract_properties.py`, `run_conformers.sh` to `/home/yo73juc/molcurator/`.

## One molecule on a compute node

```bash
python /home/yo73juc/molcurator/conformer_pipeline.py \
 --id pyridine --smiles 'c1ccncc1' \
 --xtb /vast/yo73juc/miniconda3/envs/cresta/bin/xtb \
 --orca /work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca \
 --out /work/AG_Presselt/MolCurator/conformer_test/pyridine
```

## Array job

`ROOT` must contain `molecules.csv` with `molecule_id,smiles`. Submit initial two jobs:

```bash
cd /work/AG_Presselt/MolCurator/qm9_200
sbatch --export=ALL,ROOT="$PWD" --array=0-1%2 /home/yo73juc/molcurator/run_conformers.sh
```

These are NEW conformer-aware calculations, not replacements for the existing single-conformer jobs. Limit concurrency according to cluster policy. Avoid launching the full pool until a couple of molecules succeed.

## Limitations

- Intended for neutral closed-shell molecules with common elements; charge/spin and stereochemistry require further validation.
- Greedy RMSD clustering and fixed energy windows are heuristics, not proof of exhaustive conformer sampling. The RMSD compares heavy atoms after symmetry matching.
- FF and GFN2-xTB energy rankings are method-dependent. Structural clustering is repeated because optimized conformers can merge.
- xTB orbital energies and PBE0 Kohn–Sham orbital energies are not directly equivalent; S1 is vertical absorption energy, not fluorescence.
- Doesn't perform automated failure retries; failures get summary and per-conformer logs.
- `conformer_properties.csv` has one row per selected conformer, so do not randomly split conformers of the same molecule across ML train/test sets.
- Check ORCA logs for convergence and method compatibility before treating all labels as production-quality.
