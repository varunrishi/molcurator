"""Starting, stopping and resuming agent runs as separate processes.

Each run is the existing command `molcurator run ...`, started in its own process group, so:
- a long run never blocks the API server;
- "stop" sends SIGINT, like pressing Ctrl-C in a terminal. The agent has saved a checkpoint
  after every finished step, so the run can be resumed later. The step in progress does not
  always stop on SIGINT (RDKit handles Ctrl-C itself during conformer embedding: it cancels
  that embedding and returns normally, so PREDICT just moves on to the next molecule). So
  after STOP_GRACE_SECONDS the run and the xtb/orca processes it started are killed; the
  interrupted step runs again on resume;
- runs keep going if the API server restarts (their status is kept in <runs_root>/.api/).

Bookkeeping per run, in <runs_root>/.api/:
  <run_id>.json         pid, command, start/end time, exit code, whether a stop was requested
  <run_id>.log          everything the agent process printed (appended on resume)
  <run_id>.config.yaml  the config the run was started with
"""
import json
import os
import secrets
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from molcurator.config import RunConfig

from .run_files import check_id
from .settings import Settings

STOP_GRACE_SECONDS = 10  # after a stop request, force-kill a run that has not exited by then


class RunConflict(Exception):
    """The request cannot be done in the run's current state (HTTP 409)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()  # one start/resume/stop at a time, so the run limit holds
        self._procs: dict[str, subprocess.Popen] = {}  # runs started by this server process

    # ------------------------------------------------------------------ bookkeeping files
    def _record_path(self, run_id: str) -> Path:
        return self.settings.api_dir / f"{run_id}.json"

    def log_path(self, run_id: str) -> Path:
        return self.settings.api_dir / f"{check_id(run_id)}.log"

    def _read_record(self, run_id: str) -> dict | None:
        path = self._record_path(run_id)
        return json.loads(path.read_text()) if path.is_file() else None

    def _write_record(self, run_id: str, record: dict) -> None:
        path = self._record_path(run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2))
        tmp.replace(path)  # atomic: a reader never sees half a file

    # ------------------------------------------------------------------ process state
    def _alive(self, run_id: str, record: dict) -> bool:
        proc = self._procs.get(run_id)
        if proc is not None:
            return proc.poll() is None
        pid = record.get("pid")
        if not pid or record.get("exit_code") is not None:
            return False
        try:
            os.kill(pid, 0)  # signal 0: only checks that the process exists
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        cmdline = Path(f"/proc/{pid}/cmdline")  # guard against the pid being reused by another program
        return run_id in cmdline.read_bytes().decode(errors="ignore") if cmdline.exists() else True

    def process(self, run_id: str) -> dict:
        """What the API knows about the run's process. "tracked" is False for runs it did not start."""
        record = self._read_record(run_id)
        if record is None:
            return {"tracked": False, "alive": False, "stop_requested": False, "exit_code": None}
        return {"tracked": True, "alive": self._alive(run_id, record),
                "stop_requested": record.get("stop_requested", False), "exit_code": record.get("exit_code")}

    def running_ids(self) -> list[str]:
        if not self.settings.api_dir.is_dir():
            return []
        ids = [p.stem for p in self.settings.api_dir.glob("*.json")]
        return [i for i in ids if self._alive(i, self._read_record(i) or {})]

    def _check_capacity(self) -> None:
        running = self.running_ids()
        if len(running) >= self.settings.max_runs:
            raise RunConflict(f"{len(running)} run(s) already running (limit {self.settings.max_runs}): "
                              f"{', '.join(running)}. Stop one or wait for it to finish.")

    # ------------------------------------------------------------------ actions
    def start(self, config: RunConfig, run_id: str | None = None) -> str:
        """Start a new run with an already validated config; returns its id."""
        with self._lock:
            self._check_capacity()
            run_id = check_id(run_id) if run_id else f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
            if (self.settings.runs_root / run_id).exists() or self._record_path(run_id).exists():
                raise RunConflict(f"run {run_id!r} already exists")
            self.settings.api_dir.mkdir(parents=True, exist_ok=True)
            config_file = self.settings.api_dir / f"{run_id}.config.yaml"
            config_file.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
            self._launch(run_id, [*self.settings.agent_cmd, "run", "--config", str(config_file),
                                  "--run-id", run_id, "--runs-root", str(self.settings.runs_root)])
        return run_id

    def resume(self, run_id: str) -> None:
        """Continue an interrupted run from its last finished step (`molcurator run --resume`)."""
        with self._lock:
            record = self._read_record(run_id) or {}
            if self._alive(run_id, record):
                raise RunConflict(f"run {run_id!r} is still running")
            self._check_capacity()
            self.settings.api_dir.mkdir(parents=True, exist_ok=True)
            self._launch(run_id, [*self.settings.agent_cmd, "run", "--resume", run_id,
                                  "--runs-root", str(self.settings.runs_root)])

    def stop(self, run_id: str) -> None:
        """Ask a running run to stop, like Ctrl-C. It can be resumed afterwards."""
        with self._lock:
            record = self._read_record(run_id)
            if record is None or not self._alive(run_id, record):
                raise RunConflict(f"run {run_id!r} is not running")
            record["stop_requested"] = True
            self._write_record(run_id, record)
            pid = record["pid"]
            os.killpg(pid, signal.SIGINT)  # the whole group, so a running xtb/orca stops too
        threading.Thread(target=self._force_kill_later, args=(run_id, pid), daemon=True).start()

    # ------------------------------------------------------------------ internals
    def _launch(self, run_id: str, cmd: list[str]) -> None:
        log = self.log_path(run_id).open("a")
        log.write(f"\n=== {now_iso()} {' '.join(cmd)}\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=self.settings.repo, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                start_new_session=True)  # own process group: stop() signals only this run
        self._procs[run_id] = proc
        self._write_record(run_id, {"run_id": run_id, "pid": proc.pid, "command": cmd, "started_at": now_iso(),
                                    "ended_at": None, "exit_code": None, "stop_requested": False})
        threading.Thread(target=self._wait, args=(run_id, proc, log), daemon=True).start()

    def _wait(self, run_id: str, proc: subprocess.Popen, log) -> None:
        """Record the exit code when the process ends."""
        code = proc.wait()
        log.close()
        with self._lock:
            record = self._read_record(run_id)
            if record and record.get("pid") == proc.pid:
                record.update(exit_code=code, ended_at=now_iso())
                self._write_record(run_id, record)
            if self._procs.get(run_id) is proc:
                del self._procs[run_id]

    def _force_kill_later(self, run_id: str, pid: int) -> None:
        deadline = time.time() + STOP_GRACE_SECONDS
        while time.time() < deadline:
            if not self._alive(run_id, self._read_record(run_id) or {}):
                return
            time.sleep(0.5)
        # xtb and orca are started in their own sessions, so they are not in the run's process
        # group: find them first, while they are still children of the agent.
        helpers = descendants(pid)
        for target in [pid, *helpers]:
            try:
                os.killpg(target, signal.SIGKILL)  # the checkpoint of every finished step is already saved
            except (ProcessLookupError, PermissionError):
                pass

    def log_tail(self, run_id: str, lines: int = 200) -> str:
        path = self.log_path(run_id)
        if not path.is_file():
            return ""
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])

    def record(self, run_id: str) -> dict | None:
        return self._read_record(run_id)


def descendants(pid: int) -> list[int]:
    """All processes started (directly or not) by pid, from `ps` (Linux and macOS; [] where there is none).
    /proc alone would miss them on macOS, where a stopped run then left its ORCA jobs running."""
    try:
        table = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in table.splitlines():
        try:
            child, parent = map(int, line.split())
        except ValueError:
            continue
        children.setdefault(parent, []).append(child)
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found
