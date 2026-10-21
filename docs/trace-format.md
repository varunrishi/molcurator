# Agent trace format (version 1)

Every MolCurator agent run writes a trace: one record per node it ran, in order. This document
describes the format so an evaluator can be built against it without reading the agent's code
(Phase 2, R6.3). The format was agreed with the trajectory evaluator in issue #13.

**Status: work in progress.** Version 1 covers the v1 agent: rules-only decisions, QM off.
Sections marked *not in v1* will be added later; `trace_version` changes if a change breaks
readers.

## File and writing rules

- Path: `data/runs/<run_id>/traces/trace.jsonl`, one JSON object per line.
- A line is written **when a node finishes**, never when it starts. A node interrupted mid-run
  leaves no line; on resume it runs again and writes exactly one line.
- Times are ISO 8601 UTC with milliseconds, e.g. `2026-10-21T19:33:09.308+00:00`.
- Values are plain JSON. Paths are written as strings.

## Keys on every line

| Key | Type | Meaning |
|---|---|---|
| `trace_version` | int | `1` |
| `run_id` | str | the run's id |
| `event_id` | str | `<run_id>:r<round>:<node>`, or `<run_id>:<node>` for run-level events (`run_start`); a resumed run's `run_start` is `<run_id>:run_start:resume-<n>` |
| `node` | str | node name, see below |
| `round` | int or null | round the node ran in, from 1; `null` for `run_start` |
| `started_at`, `ended_at` | str | ISO 8601 UTC |
| `status` | str | `ok`, `failed` or `skipped` |
| `reason` | str or null | why a node was skipped; `null` otherwise |
| `error` | str or null | for `failed`: `"<node>: <ExceptionType>: <message>"`; `null` otherwise |
| `inputs` | object | what the node worked on (per node, below); `{}` if nothing |
| `outputs` | object | what the node changed (per node, below); `{}` if nothing |

Decision nodes may add an `llm` key, and `run_start` adds `resumed` (see below).

## Order of lines

```
run_start
plan_round, generate, predict, train, ml_predict, screen, curate, close_round, continue_or_stop   (round 1)
plan_round, ... , continue_or_stop                                                                (round 2, ...)
write_summary                                                                                     (once, last)
```

- Each node runs once per round, so `event_id` is unique within a run.
- `continue_or_stop` is logged under the round it just closed.
- If a tool step fails as a whole (`status: failed`), the next line is `write_summary`: the rest of
  the round does not run.
- `run_start.inputs.nodes` lists the node order of the graph that actually ran. Check against it
  rather than a hard-coded list.
- A resumed run adds a `run_start` line (with `resumed: true`) between two node lines, then
  continues with the node that was interrupted. See **Resume** below.

## Statuses

| Status | When |
|---|---|
| `ok` | the node ran. A step that ran and found nothing (e.g. CURATE with no hits) is `ok`. |
| `failed` | the whole step raised; `error` says which step and why. Per-molecule failures are **not** a failed line: they appear as `failed` entries in `outputs.results`. |
| `skipped` | the node had nothing to do. `reason` is one of: `below_min_examples` (TRAIN: fewer xTB values than `train.min_examples`), `no_candidates_left` (ML PREDICT: every candidate got xTB), `empty_qm_batch` (VALIDATE, *not in v1*). |

## Per-molecule results

Tool nodes put one compact entry per molecule they changed in `outputs.results`:

```
[candidate_id, status, value_or_error]
```

- Entries are **sorted by candidate id**. PREDICT also calls xTB in id order.
- `status` is the molecule's status after the node, e.g. `predicted`, `failed`, `screened_in`.
- For a `failed` molecule the third item is the error text; otherwise it is the node's value:

| Node | Value |
|---|---|
| `generate` | canonical SMILES |
| `predict` | xTB value (target units) |
| `ml_predict` | ML estimate |
| `validate` | QM value (*not in v1*) |
| `screen`, `curate` | `null`; the status is the result |

Only molecules the node **changed** are listed. Duplicates skipped by PREDICT, and failed molecules
that SCREEN leaves alone, are absent from that node's list.

## Inputs and outputs per node

| Node | `inputs` | `outputs` |
|---|---|---|
| `run_start` | `config` (the full run config), `nodes` (graph order) | `{}` |
| `plan_round` | `{}` | `round_plan` (`parents` ids, `generator`, `n_candidates`, `mutation_strength`, `reason`), `qm_batch` (`[]`, reset each round) |
| `generate` | `round_plan` | `results` |
| `predict` | `candidate_ids` (the seeded random xTB sample, at most `predict.n_xtb`) | `results` |
| `train` | `{}` | `model` (`model_path`, `n_examples`, `metrics`) |
| `ml_predict` | `candidate_ids` | `results` |
| `screen` | `candidate_ids` | `results` |
| `curate` | `candidate_ids` (the hits) | `dataset_size` (total so far), `results`; `{}` when nothing was curated |
| `close_round` | `{}` | `round_stats`: this round's counts (`generated`, `duplicates`, `xtb_runs`, `ml_predicted`, `unscored`, `failed`, `screened_in`, `selected`, `qm_calls`, `hits`) |
| `continue_or_stop` | `{}` | `round` (the next round) when continuing, or `stop_reason` |
| `write_summary` | `{}` | `stop_reason` |

`stop_reason` is one of `target_dataset_size`, `max_rounds`, `max_qm_calls`, `max_wall_time`
(a budget), `llm` (the decider stopped early) or `error`.

## The `llm` block (decision nodes)

Present on `plan_round`, `continue_or_stop` and `write_summary` **only when the decider was
asked**. `continue_or_stop` has none when a budget limit ended the run, since budgets are checked
in code before the decider.

| Key | Meaning |
|---|---|
| `decision` | the parsed decision |
| `source` | `llm` or `rule` |
| `fallback` | why a rule decided: `rules_mode`, `invalid_answer`, `timeout`, `api_error`; `null` if the LLM decided |
| `retried` | the LLM's first answer was invalid and it was asked again |
| `prompt`, `raw_response` | the LLM call; `null` for rules |
| `duration_s` | seconds the decision took |

In v1 (rules mode) every block has `source: rule` and `fallback: rules_mode`.

## The `run_start` line

The first line of every trace. `inputs.config` holds the full settings, which explain absent or
skipped steps: with `qm.enabled: false` there are no QM lines; `train.min_examples` explains a
skipped TRAIN; `predict.n_xtb` bounds PREDICT's sample; `budget` holds the limits. `resumed` is
`false` for a new run.

## Resume

`molcurator run --resume <run_id>` continues an interrupted run (Ctrl-C, a killed process) from its
last finished node, using the run's saved `config.yaml`.

- It first writes a `run_start` line with `resumed: true` and the id
  `<run_id>:run_start:resume-<n>` (`resume-1` for the first resume, `resume-2` for the next, ...).
- The node that was interrupted wrote no line (lines are written when a node finishes), so it runs
  again and writes its line once.
- A node never writes a second line: if a run was killed after a node wrote its line but before the
  state was saved, the repeated node's line is skipped. Every `event_id` stays unique.
- Time spent stopped does not count against `budget.max_wall_time`: only running time does.
- A run that already reached `write_summary` (including one ended by a failed step) cannot be
  resumed.

## Not in v1

- QM nodes (`select_qm_batch`, `approve_qm`, `validate`) and their lines.
- Per-item `electronic_calls_attempted` / `cache_hit` for VALIDATE: needs a tool-contract change.
  The agent caches nothing, so QM calls equal the batch size (`round_stats.qm_calls`).
- `provider` and `model` in the `llm` block (with the LLM decider).

## Example

From a one-round run with the fake test tools and 4 candidates (`run_start.inputs.config` trimmed):

```json
{"trace_version": 1, "run_id": "test", "event_id": "test:run_start", "node": "run_start", "round": null, "started_at": "2026-10-21T19:33:09.297+00:00", "ended_at": "2026-10-21T19:33:09.297+00:00", "status": "ok", "reason": null, "error": null, "inputs": {"config": {"...": "full RunConfig"}, "nodes": ["plan_round", "generate", "predict", "train", "ml_predict", "screen", "curate", "close_round", "continue_or_stop", "write_summary"]}, "outputs": {}, "resumed": false}
{"trace_version": 1, "run_id": "test", "event_id": "test:r1:plan_round", "node": "plan_round", "round": 1, "started_at": "2026-10-21T19:33:09.307+00:00", "ended_at": "2026-10-21T19:33:09.307+00:00", "status": "ok", "reason": null, "error": null, "inputs": {}, "outputs": {"round_plan": {"parents": ["seed-0"], "generator": "stoned_selfies", "n_candidates": 4, "mutation_strength": 2, "reason": "Rule: repeat the previous settings with the best parents so far."}, "qm_batch": []}, "llm": {"decision": {"parents": ["seed-0"], "generator": "stoned_selfies", "n_candidates": 4, "mutation_strength": 2, "reason": "Rule: repeat the previous settings with the best parents so far."}, "source": "rule", "fallback": "rules_mode", "retried": false, "prompt": null, "raw_response": null, "duration_s": 0.0}}
{"trace_version": 1, "run_id": "test", "event_id": "test:r1:predict", "node": "predict", "round": 1, "started_at": "2026-10-21T19:33:09.309+00:00", "ended_at": "2026-10-21T19:33:09.311+00:00", "status": "ok", "reason": null, "error": null, "inputs": {"candidate_ids": ["r1-c000", "r1-c001", "r1-c002", "r1-c003"]}, "outputs": {"results": [["r1-c000", "predicted", 2.296032034264647], ["r1-c001", "predicted", 1.769685938851864], ["r1-c002", "predicted", 3.745460346855722], ["r1-c003", "predicted", 4.189157707586925]]}}
{"trace_version": 1, "run_id": "test", "event_id": "test:r1:train", "node": "train", "round": 1, "started_at": "2026-10-21T19:33:09.311+00:00", "ended_at": "2026-10-21T19:33:09.311+00:00", "status": "skipped", "reason": "below_min_examples", "error": null, "inputs": {}, "outputs": {}}
{"trace_version": 1, "run_id": "test", "event_id": "test:r1:continue_or_stop", "node": "continue_or_stop", "round": 1, "started_at": "2026-10-21T19:33:09.315+00:00", "ended_at": "2026-10-21T19:33:09.315+00:00", "status": "ok", "reason": null, "error": null, "inputs": {}, "outputs": {"stop_reason": "max_rounds"}}
```

The SMILES in the fake tools' GENERATE results (`fake-r1-000`) are placeholders; real runs record
canonical SMILES.
