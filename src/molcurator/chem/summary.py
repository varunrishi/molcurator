"""Summarize durable attempt records without counting cache hits as calculations."""
import json
import math
from pathlib import Path
from .fileio import native_path


def summarize(root):
    records = []
    errors = []
    for path in sorted(native_path(root).rglob("attempts/*/attempt.json")):
        try:
            record = json.loads(path.read_text())
            process = path.parent / "process.json"
            if process.is_file():
                record.update(json.loads(process.read_text()))
            if (not isinstance(record.get("electronic_calls_attempted", 0), int)
                    or record.get("electronic_calls_attempted", 0) not in (0, 1)
                    or not isinstance(record.get("runtime_s", 0), (int, float))
                    or not math.isfinite(record.get("runtime_s", 0))
                    or record.get("runtime_s", 0) < 0):
                raise ValueError("invalid attempt count or runtime")
            records.append(dict(path=str(path), **record))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            errors.append(dict(path=str(path), error=str(exc)))
    return dict(
        events=len(records), cache_hits=sum(bool(r.get("cache_hit")) for r in records),
        electronic_calls_attempted=sum(r.get("electronic_calls_attempted", 0) for r in records),
        by_backend={backend: sum(r.get("electronic_calls_attempted", 0)
                                for r in records if r.get("backend") == backend)
                    for backend in ("xtb", "orca")},
        failed_events=sum(r.get("status") == "failed" for r in records),
        running_or_interrupted=sum(r.get("status") == "started" for r in records),
        runtime_s=sum(r.get("runtime_s", 0) for r in records),
        record_errors=errors, records=records)
