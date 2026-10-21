# Agent trajectory evaluation (provisional contract)

This independent evaluator checks saved events without executing the agent or
editing its tools/contracts. It is separate from the dataset evaluator PR #14.

**Trace integration is pending Varun's confirmation in issue #13.** At inspection,
`origin/agent/orchestrator` commit `4231bb0` has tool nodes but no trace writer or
`docs/trace-format.md`. This adapter is a concrete proposal for that writer, not
a claim that current runs emit this format. Rename/adapt fields in this module
once a representative trace is agreed; no orchestrator changes are included.

## Entry points

```python
from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace

events, source = load_trace("trace.jsonl")
report = evaluate_trajectory(
    events, source=source, qm_enabled=True, ml_enabled=False,
    budgets={"max_rounds": 5, "max_qm_calls": 20,
             "max_wall_time": 3600, "target_dataset_size": 10},
)
```

```bash
python scripts/evaluate_trajectory.py trace.jsonl \
  --max-rounds 5 --max-qm-calls 20 --max-wall-time 3600 \
  --target-dataset-size 10 --out trajectory-report.json
```

Use `--ml-enabled` for workflows with TRAIN/ML PREDICT; `--qm-disabled` for
screen-and-curate workflows without QM. Outputs must be new files. Input files
are never overwritten. CLI exits: 0 = checks pass on supplied evidence,
1 = detected violation, 2 = invalid file/arguments, 3 = insufficient evidence.
The JSON report carries source SHA256, policy, per-category verdicts, findings
with event IDs and stable codes, and observed run counts. Reports are deterministic.
If report writing fails, the CLI removes only the new output file it created;
existing report files and the input trace are preserved.

## Proposed event envelope

One JSON object per nonblank line, in execution order, for one complete serial run:

```json
{"trace_version":1,"run_id":"run-001","event_id":"round1-predict","node":"predict","round":1,"started_at":"2026-10-21T10:00:00Z","ended_at":"2026-10-21T10:00:01Z","status":"ok","inputs":{"candidate_ids":["a"],"calculation_fingerprints":{"a":"recipe-sha256"}},"outputs":{"results":[{"candidate_id":"a","status":"ok","value":3.2,"error":null,"xyz_path":"xyz/a.xyz"}]},"error":null}
```

Event IDs are unique across resumes; versions and run IDs must be consistent.
Round numbers are positive, sequential and nondecreasing. Timestamps are ISO 8601
with explicit timezone and represent a serial run. Concurrent workflows require a
different adapter. `status` is `ok`, `failed` (whole-step exception), or `skipped`.
Optional skipped nodes need `outputs.skip_reason`. Whole-step failures need error
text and terminate normal work; a final successful summary records stop_reason
`error`. Per-molecule failures stay inside an otherwise successful event.

Expected sequence in each round:

```text
plan_round → generate → predict → [train → ml_predict] → screen
  → [select_qm_batch → [approve_qm] → validate]
  → curate → close_round → continue_or_stop
```

ML and QM nodes are optional according to the evaluator's mode flags. Final
`write_summary` follows the last round or a whole-step failure. Missing mandatory
node records mean insufficient ordering evidence; observed backward steps,
work after stop, or work after summary are violations. Include no-op nodes with
empty input/result lists, or explicit optional skip events, so omissions are not
confused with unrecorded work.
An aborted round requires evidence only through its failed node. Missing records
in earlier rounds still produce an insufficient-evidence finding.

## Per-node evidence

| Node | Inputs | Outputs |
|---|---|---|
| plan_round | Optional decision summary | Optional plan summary |
| generate | `parents` SMILES list; `settings` serialized GenerationSettings | `candidates`: full serialized Candidate list |
| predict | Ordered `candidate_ids` | Ordered serialized Prediction objects in `results`; successful items need XYZ path |
| train | `examples`: serialized TrainingExample list | `model`: serialized TrainResult |
| ml_predict | Ordered `candidate_ids`, current trained `model_path` | Ordered Prediction `results`, without XYZ paths |
| screen | Ordered successfully predicted `candidate_ids` | `screened_ids` eligible subset |
| select_qm_batch | Optional decision summary | Ordered `candidate_ids` subset of screened IDs |
| approve_qm | Optional approval summary | Ordered `candidate_ids` subset of selected IDs |
| validate | Ordered selected/approved `candidate_ids`; `qm_method` | Ordered QMResult `results`, enriched with launch/cache fields below |
| curate | `entries`: serialized CuratedEntry list | Cumulative integer `dataset_size` |
| close_round | Optional statistics | Optional statistics |
| continue_or_stop | Optional decision summary | Boolean `continue` |
| write_summary | Optional summary context | Nonempty `stop_reason` (must be `error` after whole-step failure) |

Tool models are validated using existing schemas. Extra trace-only metadata does
not require adding fields to shared tool contracts. Record actual ordered calls,
not sorted summaries; sorting would hide ID-order violations. The evaluator
checks result cardinality/order, candidate identity/lineage, finite values,
geometry handoff, training counts/model provenance, screen/selection membership,
curation identity/evidence and plausible dataset growth. It does not open geometry
or model files, re-execute chemistry, judge the LLM's prose, or reconstruct target
screening thresholds from missing config. Dataset target correctness belongs in
the separate dataset evaluator.
When per-molecule results are absent, dependent screen/QM/curation checks remain
unassessable rather than inventing failed molecules. Explicitly failed or invalid
results still produce violations when used improperly.

## Budgets, repeated work and failures

Each QM result needs `electronic_calls_attempted` (integer 0 or 1) and should
include boolean `cache_hit`. Counts are trace extensions from chemistry attempt
records, not new QMResult fields. For a whole-step VALIDATE exception, record
the aggregate `outputs.electronic_calls_attempted` when individual results are
unavailable. Missing launch evidence yields an explicit lower-bound count and
`not_assessable` budget verdict; selected batch length is never substituted.
Observed failed launches count toward the budget; cache hits count zero.
Accounting is performed even when the call/results fail correctness checks.
A skipped VALIDATE event cannot contain recorded results or positive launch
counts: such a contradiction is flagged and observed launches are still counted.

Rounds and elapsed span are compared to limits. Wall time covers first event
start through last event end (including summary overhead); it is observed elapsed
time, not CPU usage or proof that an external child process was terminated. An
event outside the trace cannot be accounted for. `target_dataset_size` is a
stopping threshold, not a cap on accepted molecules in the final batch. New
generation after it has already been reached is flagged.

Predict/ML/QM repetition keys use canonical isomeric SMILES, tool, QM method and
optional per-candidate `inputs.calculation_fingerprints`. A fingerprint should
identify the full tool recipe (model/settings, exact geometry, code/backend
identity as relevant), not the candidate ID or only SMILES. A successful repeat
with the same recorded recipe is flagged; no recipe means a possible repeat
with insufficient evidence, since methods/settings may have changed. Changed
recipes are separate work. Explicit cache reuse with zero launches is recognized,
although repeating a workflow node can still violate ordering. Cache declarations
are reported evidence, not independent cache/log authenticity verification.

Per-molecule retry events must use `retry_of_event_id` referencing an earlier
same-node/same-round event with failed results for every retried ID. Retrying a
failed result is distinguished from repeating successful work. Whole-step failure
still terminates the run under the current spec. Failed molecules must not feed
QM or curation as successful evidence; skipping failed items while continuing
with successful ones is allowed. Failed steps without error text, continued work
after an exception, and inconsistent final stop reasons are flagged.
The referenced failure must be each ID's latest result, and retries must precede
downstream nodes. A QM retry may contain just the failed subset of the approved
batch, preserving its order and the successful prediction geometry; every new
launch still counts toward the budget. A stale failure reference cannot authorize
repeating work that has since succeeded.

## Tests and integration boundary

```bash
python -m pytest tests/test_trajectory_evaluation.py tests/test_evaluate_trajectory_cli.py -q
```

Tests use synthetic traces and the same isolated RDKit/Pydantic/pytest environment
as dataset evaluation. No LLM keys, LangGraph runtime or chemistry binaries are
needed. Synthetic passes establish evaluator behavior only. Teammate integration
still requires an agreed producer format and one representative real trace.
Partial histories, concurrent execution, distributed clock skew, model accuracy,
automatic trace collection and raw chemistry-log reconciliation are outside v1.
