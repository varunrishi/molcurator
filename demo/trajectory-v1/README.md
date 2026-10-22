# Agreed trace v1: actual-agent demo

This demo runs the upstream LangGraph agent and its actual TraceWriter, then
evaluates the resulting `traces/trace.jsonl`. It uses real STONED generation and
RDKit geometry preparation. **xTB is deliberately unavailable**, QM is disabled,
and decisions use rules. This demonstrates failure handling and honest evidence
limits, not successful property prediction or quantum validation. No fabricated
property values or fake tools are used.

The evaluator branch does not contain the newer agent implementation. Export the
exact upstream revision to a separate directory; no merge or branch switch is
needed. The demo runner launches that agent in a subprocess so its config/schema
imports remain isolated from the evaluator's imports. It disables remote tracing.

## Reproduce (PowerShell, repository root)

Python 3.12 was used for validation. Reuse the evaluation environment or create one:

```powershell
python -m venv "$env:TEMP\molcurator-trace-v1-venv"
$Py = "$env:TEMP\molcurator-trace-v1-venv\Scripts\python.exe"
& $Py -m pip install rdkit==2026.9.1 pydantic==2.14.1 pytest==9.1.1 langgraph==1.2.16 PyYAML==6.0.3 selfies==2.2.0

git fetch origin main
$AgentRevision = "ad4e119c6eb48ac716cd633c39c3db540c07508d"
$AgentSource = Join-Path $env:TEMP ("molcurator-agent-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $AgentSource | Out-Null
$Archive = Join-Path $AgentSource "source.tar"
git archive --format=tar --output="$Archive" $AgentRevision
tar -xf "$Archive" -C "$AgentSource"

$Run = "data/runs/trace-v1-demo-" + [guid]::NewGuid().ToString("N")
& $Py -B scripts/demo_trace_v1.py --agent-source "$AgentSource" --agent-revision $AgentRevision --out "$Run"
& $Py -m pip freeze | Set-Content "$Run/environment.txt"

# Independently re-read the agent-produced trace with the CLI:
& $Py -B scripts/evaluate_trajectory.py "$Run/traces/trace.jsonl" --out "$Run/evaluation-cli.json"
```

Every output directory/report must be new. The script intentionally sets XTB_BIN
to a nonexistent path inside the run directory, regardless of machine defaults.
No licensed executable or API key is needed. Dependency download needs networking;
the agent/demo itself runs locally. Timing, absolute error paths and run-directory
hashes vary; the counts below are the expected deterministic behavior.

## Captured run and expected evidence

Validated locally in `data/runs/trace-v1-demo-20261022`:

| Observation | Result |
|---|---|
| Trace origin | Actual graph at upstream `ad4e119`, actual tools/TraceWriter |
| Trace events / rounds | 11 / 1 |
| Generated molecules | 4 valid structures |
| PREDICT inputs | 2 |
| PREDICT results | 2 explicit FileNotFoundError failures |
| TRAIN | Skipped: `below_min_examples` |
| ML fallback | 2 `unscored` molecules, with null values |
| Curated dataset size | 0 |
| Stop reason | `max_rounds` |
| Available-evidence checks | pass |
| QM behavior | **not measurable**, because disabled |
| Observed QM launches | null; round-reported QM calls are separately 0 |
| Actual LLM behavior | not measurable; 2 rule decisions were recorded |

The graph handled molecular failures and stopped correctly. A passing evaluation
here does **not** mean the chemistry succeeded or that any target molecules were
found. The exact process-launch evidence is absent from compact v1; the evaluator
does not infer successful process execution from sample-size counters.

## Presentation sequence (about three minutes)

1. Show `demo-manifest.json`: source revision/file hashes and deliberate xTB absence.
2. Show `traces/trace.jsonl`: `run_start` embeds config/node order; PREDICT has compact
   failed rows; TRAIN records its top-level reason; ML marks remaining items unscored.
3. Show `evaluation-cli.json`: available ordering, correctness, budgets and failure
   checks, followed by the explicit **QM behavior: not measurable** capability.
4. Show `summary.md`: zero curated molecules and a clean max-rounds stop. Explain
   that evaluator correctness and scientific success are distinct outcomes.

Artifacts stay in the existing gitignored run directory. Source contracts, agent
code and team configuration are unchanged. The saved environment freeze supports
recreating the demonstrated installation; raw trace/report provenance includes
the actual local byte hash. For a successful physics demo, supply an independently
produced agent trace from an installation with working property tools instead.
