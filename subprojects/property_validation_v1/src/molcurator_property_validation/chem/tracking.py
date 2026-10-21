"""Atomic completion caches and per-invocation records in isolated working directories."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from rdkit import rdBase
from .settings import active_settings

POLICY_VERSION = "mmff94-single-point-v2"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def native_path(path):
    path = Path(path).resolve()
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        text = str(path)
        return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
    return path


def atomic_json(path, value):
    path = native_path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


@lru_cache(maxsize=32)
def _binary_hash(path, size, modified):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def executable_identity(key, fallback):
    resolved = shutil.which(os.environ.get(key) or fallback)
    if resolved is None:
        return {"path": None, "sha256": None}
    path = Path(resolved).resolve()
    stat = path.stat()
    return {"path": str(path), "sha256": _binary_hash(str(path), stat.st_size, stat.st_mtime_ns)}


def program_version(text, backend):
    pattern = (r"(?:xtb\s+version|\*\s*xtb\s+version)\s*[:=]?\s*v?([\d.]+[^\s*]*)"
               if backend == "xtb" else r"Program\s+Version\s*[:=]?\s*([\d.]+[^\s]*)")
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else None


def calculate(folder, backend, args, inputs, parser, runner, settings, context):
    """Reuse only fully validated successful output; failed/interrupted work is retried.

    Cache hits are separate zero-launch events. Each fresh attempt has its own cwd,
    so interrupted or concurrent invocations cannot contaminate a new calculation.
    Concurrent callers may duplicate work; this is not a distributed scheduler.
    """
    folder = native_path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = backend.upper() + "_BIN"
    identity = executable_identity(key, backend)
    recipe = dict(policy=POLICY_VERSION, rdkit_version=rdBase.rdkitVersion,
                  backend=backend, executable=identity, arguments=args,
                  input_sha256={name: digest(data) for name, data in inputs.items()},
                  settings=settings.model_dump(), context=context,
                  runtime_environment={k: os.environ.get(k, "") for k in
                      ("PATH", "LD_LIBRARY_PATH", "LOADEDMODULES", "DYLD_LIBRARY_PATH")})
    fingerprint = digest(json.dumps(recipe, sort_keys=True).encode())
    attempt_id = uuid.uuid4().hex
    work = folder / "attempts" / attempt_id
    work.mkdir(parents=True)
    record = dict(attempt_id=attempt_id, candidate_id=context["candidate_id"], backend=backend,
                  fingerprint=fingerprint, recipe=recipe, status="started", cache_hit=False,
                  started_at=datetime.now(timezone.utc).isoformat(), process_started=False,
                  electronic_calls_attempted=0, qm_calls_attempted=0,
                  runtime_s=0.0, timeout_s=settings.timeout_s, timed_out=False,
                  program_version=None, version_status="not_reported")
    started = time.monotonic()
    log_name = backend + ".out"
    cache = folder / "cache.json"

    def save():
        atomic_json(work / "attempt.json", record)
        atomic_json(folder / "attempt.json", record)

    save()
    try:
        if settings.cache_enabled and identity["sha256"] and cache.is_file():
            try:
                saved = json.loads(cache.read_text())
                source = folder / "attempts" / saved["attempt_id"]
                # IDs are generated here; do not follow arbitrary paths in a manifest.
                if not re.fullmatch(r"[0-9a-f]{32}", saved["attempt_id"]):
                    raise ValueError("invalid cached attempt id")
                raw = (source / log_name).read_bytes()
                source_record = json.loads((source / "attempt.json").read_text())
                valid = (saved["fingerprint"] == fingerprint
                         and source_record["status"] == "ok"
                         and source_record["fingerprint"] == fingerprint
                         and digest(raw) == saved["log_sha256"]
                         and all((source / name).read_bytes() == data for name, data in inputs.items()))
                if valid:
                    value = parser(raw.decode(errors="replace"))
                    if not math.isfinite(value) or value != saved["value"]:
                        raise ValueError("cached value mismatch")
                    record.update(status="ok", cache_hit=True, value=value,
                                  reused_attempt_id=saved["attempt_id"],
                                  program_version=source_record.get("program_version"),
                                  version_status=source_record.get("version_status", "not_reported"))
                    shutil.copyfile(source / log_name, folder / log_name)
                    return value
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Malformed, incomplete, changed or failed artifacts are never reused.
        for name, data in inputs.items():
            (work / name).write_bytes(data)
        token = active_settings.set(settings)
        try:
            runner(key, backend, args, work, work / log_name)
        finally:
            active_settings.reset(token)
        if any((work / name).read_bytes() != data for name, data in inputs.items()):
            raise ValueError("electronic backend changed a single-point input file")
        raw = (work / log_name).read_bytes()
        value = parser(raw.decode(errors="replace"))
        record.update(status="ok", value=value)
        if identity["sha256"] and settings.cache_enabled:
            # Publish cache only after the successful attempt record is durable.
            record["pending_cache"] = dict(fingerprint=fingerprint, attempt_id=attempt_id,
                                           log_sha256=digest(raw), value=value)
        return value
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        process = work / "process.json"
        if process.is_file():
            record.update(json.loads(process.read_text()))
        if (work / log_name).is_file():
            text = (work / log_name).read_text(errors="replace")
            version = program_version(text, backend)
            record.update(program_version=version,
                          version_status="reported_in_output" if version else "not_reported")
            shutil.copyfile(work / log_name, folder / log_name)
        record["qm_calls_attempted"] = record["electronic_calls_attempted"] if backend == "orca" else 0
        record.update(elapsed_s=time.monotonic() - started,
                      finished_at=datetime.now(timezone.utc).isoformat())
        pending = record.pop("pending_cache", None)
        save()
        if pending is not None:
            atomic_json(cache, pending)
