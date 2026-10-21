# Stage protocol / outputs

| Stage | Command | Input | Main output | QC gate |
|---|---|---|---|---|
| Proposal I | `generate1` | seed SMILES, novelty exclusions | `design_qm9_0023/molecules.csv` | canonical SMILES; neutral C/N/O/F; valid RDKit geometry |
| xTB I | `submit-xtb1` | candidate SMILES | `xtbopt.xyz`, `xtb.out` | convergence; HOMO/LUMO/gap/dipole |
| Ranking I | `rank1` | xTB results, frozen RF | `ranked_candidates.csv`, `orca_selected.csv` | check novelty, descriptors, selection |
| ORCA I | `submit-orca1` | selected xTB geometries | `excited.out`, `properties.csv` | finished ORCA; TDDFT roots; S₁ numeric |
| Validation I | `evaluate1` | selected and parsed QC | `validated_designs.csv`, plots | target hit and error reporting |
| Audit II | `audit2` | saved model, 8 new labels | logs | **MUST pass prediction match** |
| Train II | `fit2` | 257 original training + 8 new QC | `combined_rf_augmented.joblib` | preserve 19 held-out and 48 external |
| Proposal II | `generate2` | seed + validated anchors | `design_iteration2/molecules.csv` | no repeats or data leakage |
| xTB II | `submit-xtb2` | new candidates | optimized geometries, descriptors | success/coverage |
| Ranking II | `rank2` | 2 models and candidate descriptors | `orca_selected.csv` | target deviation + applicability range + diversity |
| ORCA II | `submit-orca2` | 12 selected | `excited.out`, `properties.csv` | successful ORCA |
| Validation II | `evaluate2` | 12 new QC labels | `validated_iteration2.csv`, plot | compare both models **on same new candidates** |

The scripts are a faithful reference implementation of the demonstrated workflow but only partial automation. Scheduling, queue monitoring, chemical inspection and retrying unsuccessful QC jobs remain operator responsibilities. No LangGraph/Qwen3 agent or REINVENT4-trained generator is included.
