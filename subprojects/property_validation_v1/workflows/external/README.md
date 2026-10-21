# MolCurator: 50 new external QM9 test molecules

Select 50 unique canonical-SMILES unseen among the full 276-molecule dataset; calculate new labels; evaluate frozen trained models without fitting or modifying them.

Commands after unzipping into `/home/yo73juc/molcurator`:

```bash
conda activate /home/yo73juc/miniforge3/envs/rdkit_env
python /home/yo73juc/molcurator/molcurator_external_test/select_external.py
# Verify molecules.csv and random selections before using cluster resources.
sbatch --array=0-49%8 /home/yo73juc/molcurator/molcurator_external_test/run_array.sbatch
squeue --me
# When jobs finish:
python /home/yo73juc/molcurator/molcurator_external_test/evaluate_external.py
```

Prerequisite: `/home/yo73juc/molcurator/extract_properties.py` existing from prior pipeline. It uses the same property column names as training. `run_qc.py` uses ETKDGv3+MMFF94 once, GFN2-xTB, TDA-PBE0/def2-SVP/ORCA 6.1.1, and single-thread computations. If the original geometries were prepared using multiple ETKDG conformers or distinct optimization settings, comparability may differ. Compare geometrical prep before scientific interpretation.

If run takes more than three hours, increase job time and select a partition permitting it. Some molecules may fail and should be reported, not silently imputed for S1 target. Separate external holdout is from the same QM9 molecule source, so this is not an out-of-distribution benchmark. Reporting no overlap after canonical SMILES de-duplication does not guarantee scaffold novelty.
