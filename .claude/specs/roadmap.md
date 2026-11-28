# Roadmap

Phases 1-3 were the 20-22 Oct 2026 hackathon and are done. Phases 4-9 are the path to a published
agent: each item is tracked as a GitHub issue, and the phases are ordered so that the work which
makes later work small comes first.

## Phase 1: Tool foundations (Day 1, 20 Oct 2026) — done

Build each tool as a standalone, testable unit with a clear input/output interface.

- [x] **GENERATE**: generate new molecules from a seed molecule (STONED SELFIES + RDKit; Mol2Mol deferred).
- [x] **PREDICT**: SMILES → 3D geometry → xTB (or TD-DFT) → property extraction.
- [x] **TRAIN**: train a model for the target property on the growing dataset (CatBoost / random forest; ChemProp deferred).
- [x] **VALIDATE**: compute the target property for screened molecules with quantum chemistry (ORCA through OPI).
- [x] **CURATE**: add verified molecules to the dataset with SMILES, structure and multi-level properties.
- [x] **EVALUATE**: pipelines to evaluate the agent's trajectories and tool calls.

**Exit criteria:** each tool runs on its own for a sample seed molecule and returns structured output. Met.

## Phase 2: Agent orchestration and use cases (Day 2, 21 Oct 2026) — done

- [x] Wire the tools into a LangGraph orchestrator with LLM decision nodes, each with a rule-based fallback.
- [x] Implement the loop: generate → predict + screen → train + ML screen → validate (QM) → curate.
- [x] **Use case 1**: molecules within a specific HOMO-LUMO gap range.
- [x] **Use case 2**: candidate TADF emitters with an S1-T1 gap close to zero.
- [x] Run EVALUATE on the agent trajectories for both use cases.

**Exit criteria:** the agent produces a curated benchmark set end to end for both use cases. Met.

## Phase 3: Demo (Day 3, 22 Oct 2026) — done

- [x] Demo presentation and project video.
- [x] README, web app and API server, batch command with SLURM support.

## Phase 4: Foundations for many properties and many objectives

The blocking phase. Each item here is what keeps Phases 5-7 from becoming a fork of the pipeline,
and the uncertainty item closes a gap between what the README claims and what the code does.

- [ ] #60 **Multi-objective targets**: `target` becomes a list of objectives, each with its own window,
      unit and weight. Touches `schemas.py`, `config.py` and the screen node.
- [ ] #61 **Property registry**: properties become pluggable (compute function, unit, cost tier, backend)
      instead of the `SCALAR_PROPERTIES` tuple in `chem/properties.py`. Extends #59.
- [ ] #62 **Uncertainty-driven QM selection**: select the QM batch by model uncertainty rather than
      closeness to the target; give the default model (CatBoost) an uncertainty estimate, or document
      the restriction to the random forest. Reconcile the README and this mission with the code.
- [ ] #63 **Per-property correction framework**: generalise `scripts/fit_xtb_correction.py` beyond
      `homo_lumo_gap`, and store fitted corrections as artifacts with provenance and residual spread
      rather than literals in a run config.
- [ ] #64 **Drug-like size regime**: make `MAX_HEAVY_ATOMS` (now a constant in `tools/generate.py`) a
      per-config limit, and re-tune the xTB and QM budgets for molecules of ~35 heavy atoms.

**Exit criteria:** a run config can name two objectives of different cost tiers, and the agent
screens on both without any property-specific branching in the graph.

## Phase 5: More properties

- [ ] #65 S0→S1 excitation energy and oscillator strength as first-class targets (ORCA already parses both).
- [ ] #66 Transition dipole moment.
- [ ] #67 Ground-state dipole moment as a documented, validated target.
- [ ] #68 Cheminformatics property tool: Lipinski Ro5, logP, TPSA, HBD/HBA, QED, pKa — zero-cost RDKit
      properties that screen *before* any geometry work.
- [ ] #69 Synthesizability score (SAScore / RAscore) as both a screen and an objective.
- [ ] #70 Binding affinity: a design spike first (the config has nowhere to put a protein target), then a
      docking backend behind the VALIDATE interface.

**Exit criteria:** a medicinal-chemistry run config screens on a drug-likeness profile and an
electronic property together, and the cheap filter demonstrably cuts the QM bill.

## Phase 6: More ways to generate

The agent loop is already a genetic algorithm — best parents in, mutate, score, select, breed from the
winners — so a new generator is usually a new operator in that loop rather than a new paradigm. The
operators below differ in inductive bias on purpose: string mutation, graph crossover, fragment
replacement, and construction from reactions.

- [ ] #71 Extract the shared candidate filter and write generator contract tests. Mol2Mol (REINVENT4)
      is **not** planned; the specs that promise it are corrected under #83.
- [ ] #72 A second operator for the fragment lane: CReM, or BRICS / RECAP recombination.
- [ ] #86 GraphGA — graph crossover and mutation. Also an arm in #79, since it is the baseline that
      matches or beats much heavier generative models on goal-directed generation.
- [ ] #87 Reaction-based enumeration: robust reaction SMARTS over catalog building blocks, so every
      candidate carries a one-step route. Makes synthesizability structural rather than scored (#69).
- [ ] #73 3D-structure-aware mutation — design note first: mutate the conformer, or mutate the graph and
      re-embed?

**Exit criteria:** a run can choose its generator from the config, and the operators are compared on
the same target and budget — hits per QM call, scaffold diversity, and how many candidates survive the
filter.

## Phase 7: More models

- [ ] #74 Gaussian process regression with calibrated uncertainty (depends on the Phase 4 uncertainty work).
- [ ] #75 Graph neural network backend (ChemProp), deferred from Phase 1.
- [ ] #76 Multimodal fusion: fingerprints + descriptors + learned graph embeddings.
- [ ] #77 Model-selection policy: let the agent compare and choose models as the dataset grows.

**Exit criteria:** models are interchangeable by config, and their uncertainty is calibrated well
enough that the QM batch chosen by it beats the closeness-to-target rule.

## Phase 8: Evaluation

- [ ] #78 External benchmark harness: QM9 / MoleculeNet held-out evaluation, building on `chem/qm9.py`.
- [ ] #79 Baseline comparison: random generation, a model-only loop, and the rule-based (no-LLM) agent
      against the full agent on the same budget.
- [ ] #80 Agentic trajectory metrics: tool-call efficiency, redundant calls, decision-overturn rate, and a
      concretely defined hallucination rate (e.g. the LLM naming a candidate not in state).
- [ ] #81 RAG lookup of candidates in existing databases and literature (PubChem / ChEMBL), for
      experimental evidence without a wet lab.

**Exit criteria:** every comparative claim in the paper has a script that reproduces its numbers.
Start this phase early and in parallel: the benchmark runs take wall-clock time.

## Phase 9: Publishing

- [ ] #82 Reproducibility pack: `CITATION.cff`, an archived DOI, and one command that regenerates every
      figure and table in the paper from a tagged commit.
- [ ] #83 Keep these specs current: this roadmap, `mission.md` and `techstack.md` (which still lists
      PySCF as a dependency with no backend).
- [ ] #84 Housekeeping: implement or drop the PySCF backend, replace the placeholder TADF seed in
      `configs/tadf.yaml`, and run ruff in CI alongside pytest.

**Exit criteria:** a reviewer can clone the tagged commit, run one command, and get the paper's
numbers.
