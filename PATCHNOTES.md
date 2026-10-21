# MolCurator — Patch Notes

## Property validation and calibrated screening

**Reviewed:** 21 October 2026
**Shared branch:** `codex/calibrated-screening-v1`
**Status:** Chemistry adapters and initial calibration are operational. Full agent integration and broader scientific validation remain in progress.

### What is implemented and operable

| Component | Current capability | How to use it |
|---|---|---|
| PREDICT | RDKit conformer sampling, lowest converged FF-energy geometry, one GFN2-xTB optimization, raw orbital gap | `molcurator.tools.predict.predict(candidates, target, xyz_dir)` |
| Geometry report | FF method, unique sampled minima, selected energy, FF-based Boltzmann weight at 298.15 K | Per-molecule `geometry_report.json` and `geometry_report.md` |
| VALIDATE | One ORCA ground-state single point per selected geometry, configured functional/basis, reference orbital gap | `molcurator.tools.validate.validate(predictions, target, qm)` |
| Calibrated ranking | Frozen linear/constant corrections, stable ranking, IDs/failures retained, raw values unchanged | `molcurator.screening.ranked_predictions(...)` |
| Cluster smoke runner | One molecule through real adapters; results/logs saved; nonzero exit on failure | `scripts/smoke_homo_lumo.py` or `scripts/slurm_homo_lumo_smoke.sh` |
| Property export | Separate raw/reference/calibrated properties, method/provenance and selection metadata | `scripts/export_calibrated_properties.py`, `scripts/extract_full_properties.py` |
| Research campaigns | Calibration-panel and stratified validation preparation, SLURM execution, collection and analysis | `research/calibration24/`, `research/target_validation/` |
| Optional viewers | Read-only HTML previews of existing XYZ geometries; disabled automatically by default | `scripts/export_molecule_viewers.py` or `MOLCURATOR_VIEWERS=1` |
| Scientific report | Saved figures, metrics and interpretation | `research/property_validation_results/report/REPORT.md` |

These are callable tools and research utilities. The complete `molcurator run` command, LangGraph loop, root GENERATE/CURATE implementations, persistent calculation cache, and agent evaluator are not implemented in this branch. Historical generation/ML scripts are retained as research material, not wired into the shared agent.

### Validation completed

- Latest offline combined suite: **42/42 passed**. Tests cover adapters, failures, ID preservation, geometry handoff, calibration, exports, and viewer behavior. They use real RDKit sampling and simulated external process outputs.
- Cluster documentation reports a successful real benzene smoke run: xTB gap **4.93426034 eV**, ORCA B3LYP/def2-SVP gap **6.84730000 eV**. Raw cluster logs were not re-audited during the local review.
- Initial campaign reports **24 successful calculations**, with a fixed **16 training / 8 held-out** split. Held-out MAEs: raw **2.600 eV**, constant correction **0.695 eV**, linear correction **0.772 eV**.
- Target-enriched campaign: **568 successful xTB screens from 600 candidates**, then **60 successful stratified ORCA validations**. Metrics independently reproduced from the committed 60-row CSV:

| Estimate | Validation-sample MAE (eV) | Inverse-probability-weighted screening-pool MAE (eV) |
|---|---:|---:|
| Raw xTB | 2.231 | 2.047 |
| Constant correction | 0.396 | 0.545 |
| Linear correction | 0.364 | 0.412 |

One reference target hit was found: `pool_0359`, **3.3968 eV** in the 3.0–3.5 eV window. The 60 records have unique canonical molecular identities and complete exported HOMO/LUMO/gap/dipole, FF weight, and selection probability fields. Their sampling weights sum to 568. The earlier 276-molecule PBE0 dataset remains separate from B3LYP results.

### Supported chemistry and calibration

- Connected neutral closed-shell molecules; `homo_lumo_gap` in eV; ORCA validation backend.
- Geometry policy: lowest converged MMFF94/UFF-energy conformer, then one xTB optimization and one ORCA single point. FF Boltzmann weights refer to unique sampled FF minima, not an experimental or QM ensemble population.
- Frozen linear calibration: `DFT_pred = 0.8270780546046135 * xTB + 2.9901896256531098 eV`.
- Frozen constant correction: `DFT_pred = xTB + 2.2617441034023127 eV`.
- Calibration is specific to GFN2-xTB -> ORCA **B3LYP/def2-SVP** orbital gaps at xTB geometries. Do not transfer to PBE0, S1, fluorescence, or S1–T1.
- Linear ranking with a 0.75 eV exploratory band is provisional. One observed hit does not establish recall. Keep exploration outside that band; there is no scientifically justified hard exclusion bound.

### Using the tools inside the agent

See [AGENT_CHEMISTRY_USAGE.md](docs/AGENT_CHEMISTRY_USAGE.md) for a callable example, selection rules, budget responsibilities, artifact locations, and result mapping.

The intended integration order is:

```text
agent-generated Candidates
  -> predict(): raw xTB Prediction records and optimized XYZ
  -> calibrated ranking + exploration, with remaining QM budget enforced
  -> validate(): actual reference QMResult records
  -> reference-target acceptance -> CuratedEntry records -> persistent CURATE
```

`Prediction.value` must remain raw xTB. `QMResult.value` must remain the actual calculated reference value. Calibration is separate metadata used for prioritization. Remove/replace any earlier raw-gap hard filter before inserting this ranking, otherwise it can discard useful candidates first. The orchestration team must agree on that policy; no graph or config default changes are included here.

### What remains to be done

1. Integrate tools/ranking into the agent with method matching, exploration, cumulative budgets, traces, checkpoint/resume, and a functional CLI.
2. Implement root GENERATE and idempotent CURATE; run one complete seed-to-dataset HOMO–LUMO demonstration.
3. Add a persistent calculation cache keyed by molecular identity, geometry, method/settings and software provenance; preserve lifetime attempt counts.
4. Investigate the 32 unsuccessful xTB screens and audit provenance, parser compatibility, and convergence for broader chemistry.
5. Preserve original calibration splits/manifests and add independent validation plus uncertainty estimates; screening recall remains unresolved.
6. Add TADF only after defining supported singlet/triplet protocols. ChemProp retraining and multi-conformer aggregation remain later work.

The research campaigns are separate from the agent's default 20-QM-call budget. Successful exports and initial calibration do not imply that the whole autonomous agent or universal screening policy has been validated.

### Deployment and review

Use [the branch handoff](docs/CALIBRATED_SCREENING_HANDOFF.md) for checkout and utility commands, and [the cluster guide](subprojects/property_validation_v1/CLUSTER.md) for binary/environment configuration. The default general adapter timeout is 600 seconds; the dedicated SLURM smoke job uses 1800 seconds per external process unless overridden. No LLM/API key is required to call the chemistry adapters.

Main and the original shared property-validation branch remain unchanged by this separate branch. Merge requires the team's normal integration review.
