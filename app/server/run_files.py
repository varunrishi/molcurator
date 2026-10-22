"""Reading a run folder (data/runs/<run_id>/) into the JSON the API returns.

Everything here only reads files the agent writes; the format of traces/trace.jsonl is
documented in docs/trace-format.md. Nothing here changes a run.
"""
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from .settings import Settings

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")  # run ids and molecule ids; no "/" or ".."

# Tool nodes record one [id, status, value-or-error] entry per molecule; this is what the value means.
VALUE_FIELD = {"generate": "smiles", "predict": "xtb", "ml_predict": "ml", "validate": "qm"}
DOWNLOADS = {  # file name in the API -> path inside the run folder
    "dataset.csv": "dataset.csv",
    "dataset_ml_only.csv": "dataset_ml_only.csv",
    "summary.md": "summary.md",
    "config.yaml": "config.yaml",
    "trace.jsonl": "traces/trace.jsonl",
}


def check_id(value: str) -> str:
    if not ID_PATTERN.match(value or ""):
        raise ValueError(f"invalid id: {value!r}")
    return value


def run_dir(settings: Settings, run_id: str) -> Path:
    """The folder of an existing run; FileNotFoundError if there is none."""
    path = settings.runs_root / check_id(run_id)
    if not (path / "config.yaml").is_file():
        raise FileNotFoundError(f"run {run_id!r} not found")
    return path


def list_run_ids(settings: Settings) -> list[str]:
    """Every run folder, newest first. A run folder is any folder holding a config.yaml."""
    if not settings.runs_root.is_dir():
        return []
    runs = [p for p in settings.runs_root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / "config.yaml").is_file()]
    return [p.name for p in sorted(runs, key=lambda p: (p / "config.yaml").stat().st_mtime, reverse=True)]


def read_config(path: Path) -> dict:
    return yaml.safe_load((path / "config.yaml").read_text()) or {}


def read_events(path: Path) -> list[dict]:
    """All trace lines. The agent may be writing the last line right now, so an unreadable
    last line is skipped (it will be complete on the next read)."""
    trace = path / "traces" / "trace.jsonl"
    if not trace.is_file():
        return []
    events = []
    lines = trace.read_text().splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
    return events


def compact_event(event: dict) -> dict:
    """An event without its per-molecule lists: outputs.results becomes result_counts (e.g.
    {"predicted": 98, "failed": 2}) and inputs.candidate_ids becomes inputs.candidate_count.
    The full lists are in the raw trace (/events) and in /molecules."""
    out = {k: v for k, v in event.items() if k not in ("inputs", "outputs")}
    inputs = dict(event.get("inputs") or {})
    ids = inputs.pop("candidate_ids", None)
    if ids is not None:
        inputs["candidate_count"] = len(ids)
    out["inputs"] = inputs
    outputs = dict(event.get("outputs") or {})
    results = outputs.pop("results", None)
    out["outputs"] = outputs
    out["result_counts"] = dict(Counter(r[1] for r in results)) if results else None
    if "llm" in out and isinstance(out["llm"], dict):  # prompts can be long; ask for the raw trace to see them
        out["llm"] = {k: v for k, v in out["llm"].items() if k not in ("prompt", "raw_response")}
    return out


def _time(value: str | None) -> float | None:
    return datetime.fromisoformat(value).timestamp() if value else None


def running_seconds(events: list[dict], alive: bool) -> float:
    """Time the run has spent running. Each run_start opens a segment (a resume opens a new one);
    a segment ends at its last event, or now if the process is still running."""
    total, start, last = 0.0, None, None
    for e in events:
        if e["node"] == "run_start":
            if start is not None and last is not None:
                total += max(0.0, last - start)
            start = last = _time(e["started_at"])
        else:
            last = _time(e["ended_at"])
    if start is not None:
        end = time.time() if alive else last
        total += max(0.0, (end or start) - start)
    return total


def next_node(events: list[dict]) -> str | None:
    """The node that runs next (the one in progress while the agent runs), from the graph's node
    order in the last run_start line. None once the summary is written."""
    starts = [e for e in events if e["node"] == "run_start"]
    if not starts:
        return None
    nodes = starts[-1]["inputs"].get("nodes") or []
    steps = [e for e in events if e["node"] != "run_start"]
    if not steps:
        return nodes[0] if nodes else None
    last = steps[-1]
    if last["node"] == "write_summary":
        return None
    if last["status"] == "failed":
        return "write_summary"
    if last["node"] == "continue_or_stop":
        return "write_summary" if (last.get("outputs") or {}).get("stop_reason") else "plan_round"
    if last["node"] in nodes:
        i = nodes.index(last["node"])
        return nodes[i + 1] if i + 1 < len(nodes) else None
    return None


def dataset_rows(path: Path) -> list[dict]:
    """dataset.csv with typed values: numbers as floats, empty cells as null, validated as bool."""
    file = path / "dataset.csv"
    if not file.is_file():
        return []
    with file.open(newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ("ml", "xtb", "qm"):
            row[key] = float(row[key]) if row.get(key) not in (None, "") else None
        row["round"] = int(row["round"]) if row.get("round") else None
        row["validated"] = str(row.get("validated")).lower() == "true"
        for key, value in list(row.items()):
            if value == "":
                row[key] = None
    return rows


def best_estimate(record: dict) -> tuple[float | None, str | None]:
    """The most accurate value a molecule has, and its level: QM, else xTB, else ML (as CURATE uses)."""
    for level in ("qm", "xtb", "ml"):
        if record.get(level) is not None:
            return record[level], level
    return None, None


def in_window(value: float | None, target: dict) -> bool | None:
    if value is None:
        return None
    low, high = target.get("min"), target.get("max")
    return (low is None or value >= low) and (high is None or value <= high)


def molecules(path: Path, events: list[dict], config: dict) -> list[dict]:
    """Every molecule the run has seen, rebuilt by replaying the per-molecule trace results,
    then joined with dataset.csv for curated molecules (parent, QM method, validated flag)."""
    records: dict[str, dict] = {}
    for e in events:
        results = (e.get("outputs") or {}).get("results") or []
        for cid, status, value in results:
            rec = records.setdefault(cid, {"id": cid, "smiles": None, "round": e.get("round"), "status": None,
                                           "xtb": None, "ml": None, "qm": None, "qm_method": None,
                                           "error": None, "curated": False, "validated": False, "parent": None})
            rec["status"] = status
            if status == "failed":
                rec["error"] = f"{e['node']}: {value}"
            elif e["node"] in VALUE_FIELD:
                rec[VALUE_FIELD[e["node"]]] = value
            if e["node"] == "curate":
                rec["curated"] = True
    for row in dataset_rows(path):
        rec = records.get(row["id"])
        if rec is None:  # curated but missing from the trace (should not happen); still show it
            rec = records.setdefault(row["id"], {"id": row["id"], "status": "curated", "error": None})
        rec.update({"smiles": row["smiles"], "curated": True, "validated": row["validated"],
                    "parent": row.get("parent"), "qm_method": row.get("qm_method"),
                    "round": row.get("round") or rec.get("round")})
        for level in ("ml", "xtb", "qm"):
            if row[level] is not None:
                rec[level] = row[level]
    target = config.get("target") or {}
    xyz_dir = path / "xyz"
    out = []
    for rec in sorted(records.values(), key=lambda r: r["id"]):
        value, level = best_estimate(rec)
        rec["best_value"], rec["best_level"] = value, level
        rec["in_window"] = in_window(value, target)
        rec["has_xyz"] = (xyz_dir / f"{rec['id']}.xyz").is_file()
        out.append(rec)
    return out


def overview(run_id: str, path: Path, events: list[dict], process: dict) -> dict:
    """Status, progress and budget use of one run: what the web app's run header shows."""
    config = read_config(path)
    budget = config.get("budget") or {}
    alive = process["alive"]
    finished = next((e for e in events if e["node"] == "write_summary"), None)
    failed = next((e for e in events if e["status"] == "failed"), None)
    round_stats = [e["outputs"]["round_stats"] for e in events
                   if e["node"] == "close_round" and "round_stats" in (e.get("outputs") or {})]
    stop_reason = (finished or {}).get("outputs", {}).get("stop_reason")

    if alive:
        status = "stopping" if process["stop_requested"] else "running"
    elif finished:
        status = "failed" if stop_reason == "error" else "finished"
    elif process["tracked"]:
        status = "interrupted"  # stopped before the summary: can be resumed from its checkpoint
    else:
        status = "unknown"  # started outside the API (e.g. `molcurator run`): it may still be running

    starts = [e for e in events if e["node"] == "run_start"]
    steps = [e for e in events if e["node"] != "run_start"]
    upcoming = next_node(events) if not finished else None
    return {
        "run_id": run_id,
        "status": status,
        "resumable": status in ("interrupted", "unknown") and (path / "checkpoint.sqlite").is_file(),
        "exit_code": process["exit_code"],
        "started_at": starts[0]["started_at"] if starts else None,
        "updated_at": steps[-1]["ended_at"] if steps else (starts[-1]["started_at"] if starts else None),
        "running_seconds": running_seconds(events, alive),
        "target": config.get("target"),
        "qm_enabled": bool((config.get("qm") or {}).get("enabled")),
        "decisions": config.get("decisions"),
        "nodes": starts[-1]["inputs"].get("nodes") if starts else [],
        "current": {"node": upcoming if alive else None,
                    "round": _current_round(events)},
        "last_event": ({"node": steps[-1]["node"], "round": steps[-1]["round"], "status": steps[-1]["status"]}
                       if steps else None),
        "rounds": round_stats,
        "budget": {
            "rounds_done": len(round_stats), "max_rounds": budget.get("max_rounds"),
            "qm_calls_used": sum(r.get("qm_calls", 0) for r in round_stats), "max_qm_calls": budget.get("max_qm_calls"),
            "dataset_size": len(dataset_rows(path)), "target_dataset_size": budget.get("target_dataset_size"),
            "running_seconds": running_seconds(events, alive), "max_wall_time": budget.get("max_wall_time"),
        },
        "stop_reason": stop_reason,
        "error": failed["error"] if failed else None,
        "event_count": len(events),
        "files": {name: (path / rel).is_file() for name, rel in DOWNLOADS.items()},
    }


def _current_round(events: list[dict]) -> int | None:
    """The round in progress: after continue_or_stop chose to continue, the next one."""
    steps = [e for e in events if e["node"] != "run_start"]
    if not steps:
        return 1 if events else None
    last = steps[-1]
    nxt = (last.get("outputs") or {}).get("round") if last["node"] == "continue_or_stop" else None
    return nxt or last.get("round")


def list_item(run_id: str, path: Path, events: list[dict], process: dict) -> dict:
    """The short form of overview() used by GET /api/runs."""
    full = overview(run_id, path, events, process)
    keep = ("run_id", "status", "resumable", "started_at", "updated_at", "target", "qm_enabled",
            "decisions", "stop_reason", "error")
    item = {k: full[k] for k in keep}
    item["dataset_size"] = full["budget"]["dataset_size"]
    item["rounds_done"] = full["budget"]["rounds_done"]
    return item
