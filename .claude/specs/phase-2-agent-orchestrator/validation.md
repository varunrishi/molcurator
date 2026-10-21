# Phase 2 — Agent orchestration: Validation

Four metrics, computed by `scripts/validate_phase2.sh`. Metrics 1, 2 and 4 run offline in
seconds. Metric 3 calls Claude Haiku 4.5 (about $0.10 per validation run) and is SKIPPED,
not failed, only when `ANTHROPIC_API_KEY` is absent.

## Metric 1 — Behavioral test pass rate
- **What:** every test under `tests/agent/` passes, offline (fake tools, scripted or rule
  decisions, no xTB, PySCF or LLM).
- **How:** `uv run pytest tests/agent -q`.
- **Target:** 100%.

## Metric 2 — Requirement coverage
- **What:** every R-ID in this phase's requirements.md (38 IDs, R1.1–R9.5) is referenced by
  at least one test, in its name or docstring.
- **How:** `uv run python scripts/check_requirement_coverage.py
  .claude/specs/phase-2-agent-orchestrator/requirements.md tests/agent`. The script is shared
  by later phases: it extracts `R<group>.<n>` IDs from the requirements file, searches the
  test files, and prints any uncovered IDs.
- **Target:** 100%.

## Metric 3 — LLM decision reliability
- **What:** with real Claude Haiku 4.5 deciding and fake tools producing realistic data,
  the share of LLM decisions that are valid on the first answer, with no retry or fallback.
- **Eval set:** 10 seeded scenarios in `evals/phase2/scenarios.yaml`, 5 per use case
  (HOMO-LUMO gap, TADF). They vary how hard the target is: most candidates in the window,
  few, or none; plus a tight QM budget that forces trimming. Each runs about 3 rounds, so
  roughly 100 decisions in total (plan round, select QM batch and continue or stop per
  round, plus the summary).
- **Valid means:** the answer parses, passes the decision's Pydantic model, and passes the
  semantic checks: QM batch ids all come from the table shown, generation settings lie
  within the config's ranges, and the summary is non-empty.
- **How:** `evals/phase2/llm_reliability.py`, exposing `compute_metrics()`. It runs the
  scenarios and computes everything from the run traces (`llm.retried`, `llm.fallback`,
  `llm.duration_s`), which also checks that the traces carry what EVALUATE needs.
- **Targets:**
  - first-answer validity ≥ 95%
  - p95 decision latency ≤ 5 s (measured median today: 2.2 s)
  - 0 runs that fail to finish
  It also reports the fallback breakdown (invalid answer / timeout / API error) for
  information.
- **SKIP:** only when `ANTHROPIC_API_KEY` is not set, stated in the output.
- A missed target means fixing the prompts, summaries or decision models, not lowering the
  target.

## Metric 4 — Run robustness under faults
- **What:** across 50 seeded runs with injected faults, every run ends cleanly and leaves a
  consistent run folder.
- **Faults injected** (by seed, through `FakeToolset` options and a fake Anthropic client in
  `LLMDecider`):
  - 20% of molecules fail in PREDICT, and 10% in VALIDATE (R1.6)
  - in 10 runs, a whole tool step raises (R1.7)
  - LLM timeouts, invalid answers and API errors, each in some decisions (R3.5, R9.5)
  - in 10 runs, the run is interrupted after a random node and then resumed (R7.2)
- **Checks per run:**
  1. `run_agent` returns without raising, and the final state has a `stop_reason`.
  2. `summary.md` exists, and every `trace.jsonl` line parses and has the required keys
     from `docs/trace-format.md`.
  3. Budgets were never exceeded: QM calls ≤ `max_qm_calls`, rounds ≤ `max_rounds`.
  4. No molecule was dropped: every generated id ends in a final status.
  5. For the 10 resumed runs: the final state matches an uninterrupted run with the same
     seed, and no trace line is duplicated.
- **How:** `evals/phase2/robustness.py`, exposing `compute_metrics()`. Rules-mode and
  fake-client decisions only, so there is no API cost and it runs in seconds.
- **Target:** 50/50 runs pass every check (100%).

## `scripts/validate_phase2.sh`
1. **Preconditions:** `.venv` is present and `molcurator` imports (otherwise run
   `uv sync`). The script checks whether `ANTHROPIC_API_KEY` is set (from the environment or
   `.env`) without printing it. No other services are needed.
2. **Metrics:** runs Metrics 1–4 in order. Each reports PASS or FAIL with its value against
   the target. Metric 3 reports SKIP, with the reason, only when the key is missing.
3. **Summary:** prints a table of metric, value, target and result. Exits non-zero if any
   metric FAILs. A SKIP doesn't fail the script, but it is printed clearly.

## Definition of done for Phase 2
- `scripts/validate_phase2.sh` reports PASS for Metrics 1, 2 and 4, and PASS for Metric 3
  when run with an Anthropic key at least once before the implementation commit.
- The full test suite (`uv run pytest`) is green.
- `docs/trace-format.md` exists and matches what the traces contain.
- Specs (`Write Phase 2 (agent orchestration) constitution`) and code (`Implement Phase 2
  agent orchestration and validate all metrics`) are committed separately.
