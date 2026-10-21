# Phase 2 — Agent orchestration: Plan

## Approach

- **One LangGraph `StateGraph` with fixed edges.** Tool steps and decision nodes are graph
  nodes; the only branch is after CONTINUE OR STOP (next round or summary), and that branch
  is guarded by the budget check in code. The LLM chooses values, never edges. (R1.1, R4.3)
- **Tools are injected, not imported inside nodes.** Nodes call a `Toolset` (a dataclass
  holding the four tool functions). `Toolset.default()` binds the real functions in
  `molcurator.tools`; tests pass `FakeToolset`. This keeps the agent testable before the
  tools exist and enforces the contract in one place. (R2.2, R2.3, R9.2)
- **Every decision goes through a `Decider`.** One interface, three implementations:
  - `LLMDecider`: Claude Haiku 4.5 through the Anthropic SDK, structured output from the
    decision's Pydantic model (`client.messages.parse(..., output_format=Model)`), per-call
    timeout `llm.timeout_s` with SDK retries off, one retry on a validation error with the
    error added to the prompt, then the rule. An `openai` provider (langchain-openai) covers
    OpenAI-compatible endpoints such as local Ollama. (R3.1–R3.5, R9.1, R9.5)
  - `RuleDecider`: the fallback rules from R3.5, used for `decisions: rules` and by
    `LLMDecider` as its fallback. (R3.5, R9.4)
  - `ScriptedDecider` (tests): returns queued answers, including invalid ones, to exercise
    the retry and fallback paths. (R9.1)
  The Anthropic SDK is used directly rather than through LangChain: it is the documented way
  to get schema-validated output from Claude, and the latency check used exactly this path
  (Haiku 4.5: 2.2 s median, 3/3 valid). LangGraph does not need a LangChain chat model for
  plain function nodes.
- **Prompts are built fresh from the state.** `summaries.py` turns the state into the
  compact view each decision needs (a round-statistics block, a top-N candidate table);
  `prompts.py` holds the fixed instructions. No message history is kept. (R3.2, R3.6)
- **Molecule records in the state, geometries on disk.** The state holds a dict of molecule
  records (SMILES, round, status, xTB and QM values, `xyz_path`); XYZ files go to
  `data/runs/<run_id>/xyz/`. Records are checkpointed and resumable without extra code,
  and checkpoints stay small. A canonical-SMILES index in the state skips repeats. (R1.5, R7.1)
- **Budgets live in code.** `budgets.py` computes what is left (rounds, QM calls, dataset
  size, wall time) and trims a QM batch to fit; the graph's routing function calls it after
  every round. (R4.1–R4.4)
- **Checkpointing with `SqliteSaver`** (`langgraph-checkpoint-sqlite`) at
  `data/runs/<run_id>/checkpoint.sqlite`, thread id = run id. Resume calls the graph with the
  same thread id and no new input, which continues after the last completed node. (R7.1, R7.2)
- **Human approval with LangGraph `interrupt()`** in an APPROVE QM node that is only wired in
  when `--approve-qm` is set. The CLI shows the batch, reads accept / remove ids / reject,
  and resumes the graph with `Command(resume=answer)`. (R5.1–R5.3)
- **Tracing and progress share one event hook.** A `traced` wrapper around every node emits
  "node started" and "node finished" events with timings and a summary. `TraceWriter` appends
  the finished event to `trace.jsonl`; `ProgressReporter` (rich) prints both. A trace line
  is written only when a node finishes, so a node interrupted mid-run and re-run on resume
  writes exactly one line. (R6.1, R6.2, R7.2, R8.3)
- **Failures.** Tools report per-molecule status, and nodes copy failures into the records
  (R1.6). An exception from a whole tool step is caught by the `traced` wrapper, stored as
  `state.error`, and routes the graph straight to WRITE SUMMARY. (R1.7, R4.4)
- **Config.** `RunConfig` (Pydantic) loads the YAML: target, seeds, generator limits,
  screening margin, QM settings, budgets, decision mode, LLM overrides. Both use cases are
  just two YAML files. (R1.2, R4.1, R9.4)

## Tool contract (`schemas.py`, `tools/*.py`)

```python
class PropertyTarget(BaseModel):      # from config
    name: str                         # e.g. "homo_lumo_gap", "s1_t1_gap"
    min: float | None; max: float | None; units: str = "eV"

class Status(str, Enum): ok = "ok"; failed = "failed"

class Candidate(BaseModel):
    id: str; smiles: str; parent_smiles: str; round: int; generator: str

class Prediction(BaseModel):          # PREDICT output, one per candidate
    candidate_id: str; status: Status; value: float | None
    xyz_path: Path | None; error: str | None = None

class QMResult(BaseModel):            # VALIDATE output, one per molecule
    candidate_id: str; status: Status; value: float | None
    method: str; error: str | None = None

class CuratedEntry(BaseModel):        # CURATE input
    id: str; smiles: str; xyz_path: Path
    properties: dict[str, float]      # method -> value, e.g. {"xtb": 3.3, "dft": 3.2}
    provenance: dict[str, str]        # seed, parent, generator, round

def generate(parents: list[str], settings: GenerationSettings, round: int, rng_seed: int) -> list[Candidate]
def predict(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]
def validate(items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]
def curate(entries: list[CuratedEntry], run_dir: Path) -> int   # returns dataset size
```

The tools return one result per input molecule, never dropping any (R2.4). For TADF,
PREDICT must return an xTB-level S1-T1 estimate (e.g. sTDA-xTB); that choice belongs to the
tool, and the agent never sees property-specific code.

## State (`agent/state.py`)

```python
class MoleculeRecord(TypedDict):
    id: str; smiles: str; round: int; parent: str
    status: str            # generated | predicted | failed | screened_in | screened_out
                           # | selected | validated | curated
    xtb: float | None; qm: float | None; xyz_path: str | None; error: str | None

class AgentState(TypedDict):
    run_id: str
    round: int
    molecules: dict[str, MoleculeRecord]
    seen_smiles: set[str]
    plan: RoundPlan | None          # current round's generation settings
    qm_batch: list[str]             # ids chosen for VALIDATE this round
    qm_calls_used: int
    dataset_size: int
    round_stats: list[RoundStats]   # per round: generated, failed, screened_in, validated, hits
    stop_reason: str | None         # "llm" | "max_rounds" | "max_qm_calls" | ... | "error"
    error: str | None
    started_at: float
```

Decision models (`agent/decisions.py`): `RoundPlan`, `QMBatchDecision`,
`ContinueDecision`, `RunSummary`, each with a `reason` field.

## Trace format (`docs/trace-format.md`)

One JSON object per line in `data/runs/<run_id>/traces/trace.jsonl`:

```json
{"node": "select_qm_batch", "round": 2, "started": "...", "ended": "...", "status": "ok",
 "summary": {"candidates_shown": 20, "selected": 4},
 "llm": {"provider": "anthropic", "model": "claude-haiku-4-5", "prompt": "...",
         "raw_response": "...", "decision": {...}, "retried": false, "fallback": null,
         "duration_s": 2.1},
 "budget": {"qm_calls_left": 12, "trimmed_from": null}}
```

The `llm` key appears only on decision nodes; `fallback` names the rule used
(`"invalid_answer"`, `"timeout"`, `"api_error"`, `"rules_mode"`). (R6.1–R6.3)

## Module layout

```
src/molcurator/
├── schemas.py            tool contract models (R2.1)
├── config.py             RunConfig: YAML loading and validation (R1.2, R4.1, R9.4)
├── tools/*.py            contract signatures, raising NotImplementedError until built (R2.2)
├── agent/
│   ├── state.py          AgentState, MoleculeRecord, RoundStats
│   ├── decisions.py      decision models, Decider protocol, RuleDecider (R3, R9.4)
│   ├── llm.py            LLMDecider: Anthropic (default) and OpenAI-compatible providers (R3.5, R9.1, R9.5)
│   ├── prompts.py        fixed instructions per decision node
│   ├── summaries.py      state -> compact tables/blocks for prompts (R3.2, R3.6)
│   ├── budgets.py        remaining budget, batch trimming, stop check (R4)
│   ├── toolset.py        Toolset dataclass, Toolset.default() (R2.2)
│   ├── nodes.py          tool-step nodes + screen rule (R1)
│   ├── graph.py          build_graph(config, toolset, decider, checkpointer) (R1.1, R5, R7)
│   ├── trace.py          traced wrapper, TraceWriter (R6)
│   ├── progress.py       rich ProgressReporter (R8.3)
│   └── runner.py         run_agent(), resume_agent(), run folder setup (R7.2, R8.1, R8.4)
└── cli.py                `molcurator run` (R8.2)
docs/trace-format.md      trace schema (R6.3)
tests/agent/
├── fakes.py              FakeToolset (deterministic), ScriptedDecider
└── test_*.py             one file per module, test names cite R-IDs
```

## Dependencies

Add `anthropic` (1.17.0 resolves here), `langgraph-checkpoint-sqlite` (3.1.2) and `rich`
(15.0.0). All three resolve together with the current lock on Intel macOS. Keep
`langchain-openai` for the optional OpenAI-compatible provider.

## Sequence of work

1. **Setup follow-ups:** add the three dependencies; add `ANTHROPIC_API_KEY`, `LLM_PROVIDER`
   and `LLM_MODEL` to `.env.example`; make `setup.sh` skip Ollama when
   `LLM_PROVIDER=anthropic`; update the comments in `agent/llm.py`. — prepares R9.1
2. **Contract:** `schemas.py` models and the tool signatures (bodies raise
   `NotImplementedError`), plus `FakeToolset` in `tests/agent/fakes.py`. — R2.1–R2.4
3. **Config:** `RunConfig` and the two use-case YAML files. — R1.2, R4.1, R9.4
4. **State and budgets:** `state.py`, `budgets.py`. — R1.5, R4.1–R4.3
5. **Decisions without an LLM:** decision models, `RuleDecider`, `ScriptedDecider`. — R3.5, R9.4
6. **Tool-step nodes and the screen rule:** generate, predict, screen, validate, curate,
   with per-molecule failures. — R1.3–R1.6
7. **Graph:** `build_graph`, routing, budget-guarded loop, error route to summary; first
   end-to-end run with fakes and rules. — R1.1, R1.7, R4.3, R4.4
8. **LLM decisions:** `summaries.py`, `prompts.py`, `LLMDecider` (Anthropic, then OpenAI
   provider), retry, timeout and fallback. — R3.1–R3.6, R9.1, R9.5
9. **Traces:** `traced` wrapper, `TraceWriter`, `docs/trace-format.md`. — R6.1–R6.3
10. **Checkpoint and resume:** `SqliteSaver`, `resume_agent`, no duplicate trace lines. — R7.1, R7.2
11. **Human approval:** APPROVE QM node with `interrupt()`, CLI prompt. — R5.1–R5.3
12. **Runner, CLI and progress:** `run_agent`, run folder layout, `molcurator run`,
    rich progress. — R8.1–R8.4
13. **Validation:** `scripts/validate_phase2.sh` and the metrics in validation.md.

Each step is built under the supervised-coding rules: a plan per step, at most one function
or 20 lines per change, approval before the next change.
