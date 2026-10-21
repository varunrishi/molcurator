# Isolated HOMO–LUMO adapters

The implementations are `molcurator_property_validation.tools.predict.predict` and `molcurator_property_validation.tools.validate.validate`. They retain the shared contracts and import result models from `molcurator.schemas`; root tools are untouched.

Use [README.md](README.md) to install the isolated environment, [CLUSTER.md](CLUSTER.md) for the dedicated one-molecule job, and [docs/AGENT_CHEMISTRY_USAGE.md](docs/AGENT_CHEMISTRY_USAGE.md) for agent injection and the configured stage.

The geometry policy remains 30 ETKDGv3 conformers, converged MMFF94/UFF minimization, 0.25 Å heavy-atom RMSD deduplication, lowest FF-energy representative, then one xTB optimization and one ORCA single point. The Boltzmann weight at 298.15 K describes unique sampled FF minima. Raw and reference orbital gaps remain separate from calibrated ranking estimates.

The adapters support neutral closed-shell HOMO–LUMO gaps. Direct VALIDATE uses its supplied ORCA functional and basis; the optional calibrated stage requires its frozen B3LYP/def2-SVP method. TADF, PySCF, multi-conformer aggregation and persistent CURATE are outside this contribution.
