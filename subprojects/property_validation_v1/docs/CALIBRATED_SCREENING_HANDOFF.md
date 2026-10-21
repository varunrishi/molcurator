# Isolated calibrated-screening contribution

Shared branch: `codex/calibrated-screening-v1` in `varunrishi/molcurator`.

## Boundary

All contribution files are inside `subprojects/property_validation_v1/`. Files outside that folder match shared main at `686318f` (`v0.1-contract`). Earlier commits on this branch edited root files; the current tree restores those files and relocates the contribution without rewriting history. There is no root README, schema, config, tool, dependency, agent or test modification in the final diff against that main snapshot.

The package is **molcurator_property_validation**, not a replacement `molcurator` package. Its functions import the team's shared Candidate/Prediction/QMResult/CuratedEntry and RunConfig models. Integration is explicit: the agent maintainer chooses whether and where to inject the subproject functions. No automatic monkey-patching is performed.

## What's included

- RDKit lowest-converged-FF geometry policy and sampled-set Boltzmann reporting.
- GFN2-xTB prediction and configured ORCA reference validation.
- Frozen B3LYP gap ranking, exploration and budget-limited configured chemistry stage.
- Tests, SLURM smoke and research jobs, exports, optional viewers, committed data/reports.
- Preserved original research scripts and archived former root manifests for provenance.

See [README](../README.md) for installation, [cluster guide](../CLUSTER.md) for calculations, [agent usage](AGENT_CHEMISTRY_USAGE.md) for explicit imports and wiring, and [patch notes](../PATCHNOTES.md) for results and limitations. Run commands from the **subproject directory** unless a command explicitly says otherwise.

## Review and integration

Review the branch diff against main: every changed path should begin `subprojects/property_validation_v1/`. Use a separate checkout when comparing branches or working with historical cluster deployments. Keep raw `Prediction.value` and actual `QMResult.value` unchanged; rank separately, enforce method compatibility, preserve failures and exploration, and use actual reference values for accepted entries.

The full agent graph/CLI, generator, persistent CURATE, cumulative run ledger and cache remain team work. The stage reserves QM capacity per round and prepares entries; it is not a full orchestrator. The configured calibrated stage supports B3LYP/def2-SVP HOMO–LUMO gaps only. One observed true target hit cannot establish screening recall.

## Verification

All 55 relocated checks passed against the shared contracts. The 60-row committed validation metrics were previously independently reproduced; no QC jobs were submitted during this reorganization. Main and the earlier shared property-validation branch are not changed by publishing this branch.
