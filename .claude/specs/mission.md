# Mission

## Statement

MolCurator is an AI agent that, given a seed molecule and a desired molecular property, generates, screens, validates and curates a benchmark set of molecules that have that property.

## Problem

Building molecular benchmark sets and designing molecules with precisely tuned properties (e.g. a narrow HOMO-LUMO gap window, or a near-zero S1-T1 gap for TADF emitters) takes a lot of manual work: generating candidates, running cheap screens, choosing which candidates deserve expensive quantum chemistry, and keeping the results consistent. MolCurator automates this loop.

## Target users

- Computational chemists who need property-specific benchmark datasets.
- ML-for-chemistry researchers who need labelled data at several levels of theory.
- Materials and molecular designers looking for candidates with tuned electronic properties.

## Core capabilities

1. **Generate** candidate molecules from a seed molecule (Mol2Mol / REINVENT4 or STONED SELFIES, with RDKit).
2. **Predict** properties cheaply (SMILES → 3D geometry → xTB optimisation → property extraction) and with ML models (ChemProp), including uncertainty.
3. **Train** and retrain the ML model on the growing dataset.
4. **Validate** promising candidates, chosen by uncertainty, with more accurate quantum chemistry (PySCF / ORCA).
5. **Curate** verified molecules with SMILES, 3D structure and properties at several levels of methodology.
6. **Evaluate** the agent's trajectories and tool calls.

## Success criteria

- From one seed molecule and a property target, the agent produces a curated set of molecules that meet the target as confirmed by quantum chemistry.
- Every curated entry has its SMILES, structure, and properties from at least two levels of theory (e.g. xTB and DFT).
- Works end to end on two use cases: a HOMO-LUMO gap range, and TADF emitter candidates (S1-T1 gap ≈ 0).
- The agent's tool-call trajectories can be inspected and evaluated.

## Non-goals (hackathon scope)

- Synthesisability or retrosynthesis analysis.
- Large-scale production runs or HPC job scheduling.
- Properties beyond the two demo use cases.
