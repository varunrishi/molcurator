# Roadmap

## Phase 1: Tool foundations (Day 1, 20 Oct 2026)

Build each tool as a standalone, testable unit with a clear input/output interface.

- [ ] **GENERATE**: generate new molecules (SMILES / coordinates) from a seed molecule (Mol2Mol / REINVENT4 or STONED SELFIES + RDKit).
- [ ] **PREDICT**: SMILES → 3D geometry → xTB optimisation → property extraction.
- [ ] **TRAIN**: train a ChemProp (or similar) model for the target property on the growing dataset, with uncertainty estimates.
- [ ] **VALIDATE**: compute the target property for screened molecules with quantum chemistry (ORCA by default, or PySCF).
- [ ] **CURATE**: add verified molecules to the dataset with SMILES, structure and multi-level properties.
- [ ] **EVALUATE**: pipelines to evaluate the agent's trajectories and tool calls.

**Exit criteria:** each tool runs on its own for a sample seed molecule and returns structured output.

## Phase 2: Agent orchestration and use cases (Day 2, 21 Oct 2026)

- [ ] Wire the tools into a LangGraph orchestrator with LLM decision nodes (Claude Haiku 4.5 by default, rule-based fallback).
- [ ] Implement the loop: generate → predict + screen (xTB, threshold with margin) → validate (QM) → curate. ChemProp training and ML screening are deferred to a later phase (triggered when the dataset reaches a size threshold).
- [ ] **Use case 1**: molecules within a specific HOMO-LUMO gap range.
- [ ] **Use case 2**: candidate TADF emitters with an S1-T1 gap close to zero.
- [ ] Run EVALUATE on the agent trajectories for both use cases.

**Exit criteria:** the agent produces a curated benchmark set end to end for both use cases.

## Phase 3: Demo (Day 3, 22 Oct 2026)

- [ ] Prepare the demo presentation (motivation, architecture, results for both use cases).
- [ ] Record a short project video.
- [ ] Final README and repo cleanup.

**Exit criteria:** presentation and video are ready to submit.
