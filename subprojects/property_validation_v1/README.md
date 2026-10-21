# Property extraction and validation — iteration 1

This directory is a research subproject of MolCurator. It supplies the first implementation reference for property extraction and quantum-chemical validation. It does not replace the root MolCurator package, its agent architecture, or its roadmap.

Imported on 21 October 2026 from the local `MolCurator_Automated_GitHub` distribution. The supplied documentation is preserved in `UPSTREAM_README.md`; scripts and sample observations are retained as research provenance. Reported numerical results have not been recalculated during integration. This import is a snapshot, not a Git submodule or independently installed root package.

## First-iteration scope

- `workflows/conformers/conformer_pipeline.py`: conformer generation, force-field optimization/clustering, xTB refinement, and ORCA calculations.
- `workflows/conformers/extract_properties.py`: extract xTB and ORCA properties into CSV records.
- `workflows/external/`: independent molecular holdout selection, QC, and frozen-model evaluation.
- `examples/` and `tests/`: supplied small observations and smoke checks.

The remaining ML, multifidelity, design, iteration-2, figure, and archived workflows are supporting research history. Their inclusion does not make them part of the first-iteration agent implementation.

## Run within this subproject

From the repository root:

```bash
cd subprojects/property_validation_v1
python -m pytest -q tests
python workflows/conformers/extract_properties.py --help
```

For actual chemistry, use the subproject's `environment.yml` and read `docs/PROTOCOL.md` and `workflows/conformers/README.md`. The Bash/SLURM workflow assumes a configured Linux cluster and external xTB/ORCA installations. Historical hard-coded paths require adaptation. No QC jobs are submitted by importing this directory or running the supplied tests.

## Relationship to the main project

This is an implementation reference for the root `PREDICT`, `VALIDATE`, and `CURATE` tools. The shared data models, tool contracts, run configuration, and fake tools are available from main (tag `v0.1-contract`). No adapter is wired yet: adapt these research workflows to those contracts before connecting them to the CLI or LangGraph orchestration. Keep dependencies local until an adapter needs them; do not install the archived `molcurator` code into the main environment.

Before integration into the agent, define the property/method/unit contract, convergence and failure acceptance rules, charge/spin support, molecular identity, geometry provenance, and molecule-level dataset splitting. Preserve raw calculation paths and distinguish xTB values, DFT orbital gaps, and vertical excitation energies. The existing scripts' successful termination flags alone are not a complete scientific validation policy.

The imported distribution has no explicit license grant; its upstream README records that limitation. Preserve attribution and resolve licensing before redistribution.
