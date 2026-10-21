"""Run traces: one JSON object per line in <run_dir>/traces/trace.jsonl (Phase 2, R6).

The format is agreed with the trajectory evaluator (issue #13) and documented in docs/trace-format.md.
"""
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

TRACE_VERSION = 1
VALUE_FIELD = {"generate": "smiles", "predict": "xtb", "ml_predict": "ml", "validate": "qm"}  # per node
SKIP_REASONS = {"train": "below_min_examples", "ml_predict": "no_candidates_left", "validate": "empty_qm_batch"}


class TraceWriter:
    """Appends trace events; every line carries the same identifying keys (R6.1)."""

    def __init__(self, run_dir: str | Path, run_id: str, on_event: Callable[[dict], None] | None = None):
        self.path = Path(run_dir) / "traces" / "trace.jsonl"
        self.run_id = run_id
        self.on_event = on_event  # e.g. live progress (R8.3); called after the line is safely written

    def write(self, node: str, round: int | None, **fields) -> dict:
        """Append one event and return it; round None marks a run-level event such as run_start."""
        event_id = f"{self.run_id}:{node}" if round is None else f"{self.run_id}:r{round}:{node}"
        event = {"trace_version": TRACE_VERSION, "run_id": self.run_id, "event_id": event_id,
                 "node": node, "round": round, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:  # one open per line: a crash loses at most the line being written
            f.write(json.dumps(event, default=str) + "\n")
        if self.on_event:
            self.on_event(event)
        return event


def molecule_results(name: str, before: dict, update: dict) -> list[list]:
    """One [candidate_id, status, value or error] per molecule the node changed, sorted by id (R6.1, #13).
    Nodes return the whole molecules dict, so changes are found by comparing with the state before."""
    old, field = before["molecules"], VALUE_FIELD.get(name)
    changed = {i: m for i, m in update.get("molecules", {}).items() if old.get(i) != m}
    return [[i, m["status"], m["error"] if m["status"] == "failed" else (m[field] if field else None)]
            for i, m in sorted(changed.items())]


def node_io(name: str, before: dict, update: dict) -> dict:
    """status, reason, error, inputs and outputs for one node's trace line, from its state change (R6.1, #13)."""
    line = {"status": "ok", "reason": None, "error": None, "inputs": {}, "outputs": {}}
    if update.get("error"):  # guarded caught a whole-step failure (R1.7)
        return {**line, "status": "failed", "error": update["error"]}
    if not update and name in SKIP_REASONS:  # nothing to do this round
        return {**line, "status": "skipped", "reason": SKIP_REASONS[name]}
    results = molecule_results(name, before, update)
    if name == "generate":
        line["inputs"]["round_plan"] = before["round_plan"]  # parents and generation settings
    elif results:
        line["inputs"]["candidate_ids"] = [r[0] for r in results]
    line["outputs"] = {k: v for k, v in update.items() if k not in ("molecules", "round_stats")}
    if "round_stats" in update:
        line["outputs"]["round_stats"] = update["round_stats"][-1]  # just this round, not the history
    if results:
        line["outputs"]["results"] = results
    return line


class RecordingDecider:
    """Passes every call to the real decider and keeps the last Decided, so the trace can record how
    a decision was made (prompt, fallback, duration); the decision nodes themselves stay unchanged (R6.2)."""

    def __init__(self, decider):
        self.decider, self.last = decider, None

    def __getattr__(self, method: str):  # plan_round, select_qm_batch, continue_or_stop, write_summary
        def call(state, config):
            self.last = getattr(self.decider, method)(state, config)
            return self.last
        return call

    def take(self):
        """The decision made since the last take(), or None if the node did not ask the decider."""
        last, self.last = self.last, None
        return last


def now_iso() -> str:
    """The current time in ISO 8601 UTC with milliseconds, the trace's time format."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def traced(name: str, node: Callable[[dict], dict], writer: TraceWriter,
           recorder: RecordingDecider | None = None) -> Callable[[dict], dict]:
    """Run a node, then write its trace line; written only once it finishes, so a resumed node
    that is run again still leaves exactly one line (R6.1, R7.2). Decision nodes pass their
    recorder, so their line also says how the decision was made (R6.2)."""
    def run(state: dict) -> dict:
        started_at = now_iso()
        update = node(state)
        decided = recorder.take() if recorder else None
        extra = {"llm": {**vars(decided), "decision": decided.decision.model_dump()}} if decided else {}
        writer.write(name, state["round"], started_at=started_at, ended_at=now_iso(),
                     **node_io(name, state, update), **extra)
        return update
    return run


def write_run_start(writer: TraceWriter, config, nodes: list[str], resumed: bool = False) -> dict:
    """The first line of every trace: the full settings and the graph's node order, so an evaluator can
    explain absent steps (e.g. no VALIDATE with qm.enabled false) and check the order (R6.1, #13)."""
    now = now_iso()
    return writer.write("run_start", None, started_at=now, ended_at=now, status="ok", reason=None, error=None,
                        inputs={"config": config.model_dump(mode="json"), "nodes": nodes},
                        outputs={}, resumed=resumed)
