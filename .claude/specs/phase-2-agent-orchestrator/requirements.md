# Phase 2 — Agent orchestration: Requirements

Scope: build the LangGraph agent in `src/molcurator/agent/` that runs a fixed, deterministic
workflow of tool steps, with a fast LLM (Claude Haiku 4.5 by default) making the
decisions at four decision nodes, and a rule-based fallback for each. The tools are assumed to exist; this phase defines the
contract they implement and tests the agent against fakes that follow it.
xTB is the only screening method in this phase. ChemProp training is deferred.

Workflow of one run:

```
PLAN ROUND [LLM] → GENERATE → PREDICT (xTB, all candidates) → SCREEN (rule)
  → SELECT QM BATCH [LLM] → (optional human approval) → VALIDATE (QM) → CURATE
  → CONTINUE OR STOP [LLM] ──continue──► next round
                           └─stop─────► WRITE SUMMARY [LLM] → END
```

## R1 — Workflow
- R1.1 Each round runs the tool steps in the fixed order above. The order is defined by
  graph edges in code and cannot be changed by the LLM.
- R1.2 The agent works for any target property in the config (property name, range or
  threshold, units). Both use cases (`configs/homo_lumo.yaml`, `configs/tadf.yaml`) run with
  the same code, differing only in config.
- R1.3 Round 1 generates from the seed molecule(s) in the config. Later rounds generate
  from the parents chosen in that round's plan (R3.1).
- R1.4 SCREEN is a rule, not an LLM call: a candidate passes when its xTB value lies in the
  target window widened by the config's `screening.margin`. The margin exists because xTB
  values are systematically offset from QM values.
- R1.5 Molecules already seen in the run, compared by canonical SMILES, are not predicted
  or validated again.
- R1.6 A failure on one molecule in any tool (e.g. xTB does not converge) is recorded and
  that molecule is skipped. The round continues with the rest.
- R1.7 If a tool step fails as a whole (raises), the run stops cleanly. It records the
  error in the trace, saves the checkpoint, and still writes the summary.

## R2 — Tool contract
- R2.1 `schemas.py` defines the Pydantic models shared by agent and tools: `PropertyTarget`,
  `Candidate`, `PropertyValue`, `Prediction`, `CuratedEntry`, and per-molecule status.
- R2.2 Each tool is a plain typed function with the signature fixed in this phase's
  plan.md: `generate`, `predict`, `validate`, `curate`. The agent calls tools only
  through these signatures.
- R2.3 A fake implementation of every tool, following the same signatures, ships with the
  tests. It is deterministic for a given random seed, so the agent can be tested without
  RDKit generation, xTB or PySCF.
- R2.4 Tools return results for the molecules they were given, each with a success or
  failure status. They never drop molecules silently.

## R3 — LLM decision nodes
Every decision node sends the LLM a compact summary built from the state (never raw tool
output) and asks for a structured answer validated against a Pydantic model.
- R3.1 **Plan round:** the LLM chooses the generation settings for the round: generator,
  number of candidates, mutation strength, and parent molecules (from the seed, the curated
  set, or this run's best xTB candidates). Values outside the allowed ranges in the config
  are rejected.
- R3.2 **Select QM batch:** the LLM chooses which screened candidates go to VALIDATE, with a
  short reason. It sees a table of at most `llm.max_table_rows` candidates (id, xTB value,
  distance to target, similarity to the seed). The batch must contain only ids from that
  table.
- R3.3 **Continue or stop:** after CURATE, the LLM decides whether to run another round,
  with a short reason, based on round statistics (hit rate, budget used, dataset size).
- R3.4 **Write summary:** at the end of the run, the LLM writes a short report of what the
  agent did and why. It is saved as `summary.md` in the run folder.
- R3.5 If the LLM's answer does not parse or fails validation, the node retries once with
  the validation error added to the prompt. If it still fails, the node uses a fixed
  fallback rule:
  - plan round: repeat the previous settings (round 1: config defaults)
  - select QM batch: closest to the target first, up to the remaining budget
  - continue or stop: continue while any budget remains
  - summary: a template filled from the run statistics
- R3.6 Each LLM call's prompt is built fresh from the state. Message history does not
  accumulate across nodes or rounds.

## R4 — Budgets and stopping
- R4.1 The config sets `max_rounds`, `max_qm_calls`, `target_dataset_size` and
  `max_wall_time`. These limits are enforced in code, whatever the LLM decides.
- R4.2 A QM batch larger than the remaining QM budget is cut down to fit, keeping the
  LLM's order. This is recorded in the trace.
- R4.3 The run stops after the current round when any limit is reached, even if the LLM
  chose to continue.
- R4.4 Every run ends with a final state that records why it stopped (LLM decision, a named
  budget, or an error) and writes the summary (R3.4).

## R5 — Human approval before QM
- R5.1 With approval enabled (`--approve-qm`, off by default), the graph pauses after
  SELECT QM BATCH and shows the batch.
- R5.2 The person can accept the batch, remove candidates, or reject it. A rejected batch
  skips VALIDATE for that round. The decision is recorded in the trace.
- R5.3 With approval off, the run never blocks waiting for input.

## R6 — Traces
- R6.1 Every node writes one JSON line to `data/runs/<run_id>/traces/trace.jsonl`. Each line
  holds the node name, round, start and end times, inputs and outputs (summaries, not
  full molecule lists), and status.
- R6.2 LLM node records also hold the prompt, raw response, parsed decision, whether a
  retry or fallback was used, and the call duration.
- R6.3 The trace format is documented, so EVALUATE can be built against it without reading
  agent code.

## R7 — Checkpoint and resume
- R7.1 The agent state is checkpointed after every node, in the run folder.
- R7.2 `molcurator run --resume <run_id>` continues an interrupted run from its last
  completed node. It does not redo finished tool steps or duplicate trace lines.

## R8 — Entry points and progress
- R8.1 `run_agent(config, ...)` runs the agent from Python and returns the final state.
- R8.2 `molcurator run --config <file>` runs it from the command line, with
  `--approve-qm`, `--resume <run_id>` and `--run-id <id>` options.
- R8.3 While running, the terminal shows live progress: each node as it starts and ends,
  each LLM decision with its reason, and the round statistics.
- R8.4 Each run writes its outputs to its own `data/runs/<run_id>/` folder: config copy,
  curated dataset, traces, checkpoint and summary.

## Cross-cutting
- R9.1 The decision model comes from `LLM_PROVIDER` (`anthropic` default, or `openai` for an
  OpenAI-compatible endpoint) and `LLM_MODEL` (default `claude-haiku-4-5`), from env or
  `.env`; the run config can override them. Tests run without any LLM, using a scripted
  fake LLM.
- R9.4 The run config's `decisions: llm | rules` selects the mode. In `rules` mode every
  decision node uses its fallback rule (R3.5) and no LLM is called.
- R9.5 Each LLM call has a hard timeout (config `llm.timeout_s`, default 10 s). On timeout
  or an API error, the node uses its fallback rule and records this in the trace.
- R9.2 The whole agent test suite runs offline, without xTB, PySCF or an LLM.
- R9.3 Modules have docstrings explaining their purpose. Comments explain the non-obvious
  why.

## Out of scope for Phase 2
- Implementing the tools themselves (generate, predict, validate, curate). They are built
  against R2's contract by the tool work.
- ChemProp training and ML screening. Planned for a later phase, triggered when the dataset
  reaches a size threshold. The workflow should leave room for a TRAIN step after CURATE.
- The EVALUATE tool's metrics. This phase only produces the traces it reads (R6).
- Multi-seed campaigns, parallel tool execution, HPC job scheduling.
- A web UI. Progress is shown in the terminal only.
