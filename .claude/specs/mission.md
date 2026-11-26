# Mission

## Statement

MolCurator is an AI agent that, given a seed molecule and one or more desired molecular properties,
generates, screens, validates and curates a benchmark set of molecules that have those properties.

The workflow is a fixed, deterministic sequence of tool steps (a LangGraph graph). A fast language
model, Claude Haiku 4.5 by default, makes the judgement calls inside it: how to generate each round,
which candidates deserve expensive quantum chemistry, when to stop, and how to summarise the run.
Each decision has a rule-based fallback, so a run also works without any LLM — which also makes the
rule-based mode the natural ablation arm when measuring what the LLM contributes.

## Problem

Building molecular benchmark sets and designing molecules with precisely tuned properties takes a lot
of manual work: generating candidates, running cheap screens, choosing which candidates deserve
expensive quantum chemistry, and keeping the results consistent. MolCurator automates this loop.

The loop is the same whether the target is an electronic property of an emitter (a narrow HOMO-LUMO
gap window, a near-zero S1-T1 gap) or a profile of a drug-like small molecule (an excitation energy
*and* a logP window *and* a synthesizability floor). What changes is the number of objectives, the
cost of each property, and how many of them can be answered without quantum chemistry at all.

## Target users

- Computational chemists who need property-specific benchmark datasets.
- ML-for-chemistry researchers who need labelled data at several levels of theory.
- Materials and molecular designers looking for candidates with tuned electronic properties.
- Medicinal chemists screening small molecules against a multi-property profile.

## Core capabilities

Built and in use today:

1. **Generate** candidate molecules from a seed molecule (STONED SELFIES, with RDKit for
   sanitisation and deduplication).
2. **Predict** a property cheaply: SMILES → MMFF94 geometry → GFN2-xTB, or B97-3c TD-DFT through
   ORCA for targets xTB cannot give (S1-T1). Cheap values are corrected onto the accurate level
   before anything compares them (`predict.correction`).
3. **Train** a model on the growing dataset (CatBoost by default, random forest or a size-only
   ridge baseline as alternatives) and score the remaining candidates with it.
4. **Validate** screened candidates with more accurate quantum chemistry (ORCA through OPI).
5. **Curate** verified molecules with SMILES, 3D structure and properties at several levels of
   theory, plus provenance.
6. **Evaluate** the agent's trajectories and the curated dataset, through two standalone evaluators
   that read saved records and never re-run the agent.
7. **Decide** at fixed points in the workflow with an LLM (Claude Haiku 4.5, ~2 s per decision) or
   with rules (<1 ms), selectable per run.

Planned (see the roadmap; each is an open gap, not a current capability):

8. **Multiple objectives at once**, rather than one scalar window per run.
9. **Uncertainty-driven validation**: today the rules pick the QM batch by closeness to the target,
   and model uncertainty is only available for the random forest. Selecting by calibrated
   uncertainty is Phase 4 work.
10. **Cheap non-QM properties** (Lipinski/Ro5, logP, TPSA, QED, synthesizability) as a filter that
    runs before any geometry work.
11. **More generators** (Mol2Mol, fragment recombination, 3D-aware mutation) and **more models**
    (Gaussian process, graph neural network) behind the same interfaces.

## Success criteria

Met:

- From one seed molecule and a property target, the agent produces a curated set of molecules that
  meet the target as confirmed by quantum chemistry.
- Every curated entry has its SMILES, structure, and properties from at least two levels of theory.
- Works end to end on two use cases: a HOMO-LUMO gap range, and TADF emitter candidates.
- The agent's tool-call trajectories can be inspected and evaluated.

For publication:

- The agent beats documented baselines — random generation, a model-only loop, and the rule-based
  (no-LLM) agent — on the same budget, measured not asserted.
- Property predictions are validated against an external held-out dataset (QM9 / MoleculeNet), not
  only against the project's own calculations.
- Every claim in the paper is reproducible from a tagged commit with one command.
- Trajectory quality is quantified: tool-call efficiency, redundant work, and how often an LLM
  decision has to be overridden by its rule.

## Non-goals

- Retrosynthesis route planning. A synthesizability *score* is in scope; planning a route is not.
- Wet-lab validation. The project looks candidates up in existing databases and literature instead.
- Training foundation models. MolCurator trains small models on its own growing dataset and calls
  pretrained ones; it does not pretrain.
- A general-purpose chemistry chat agent. The graph stays a fixed sequence of tool steps with an
  LLM deciding inside it.
