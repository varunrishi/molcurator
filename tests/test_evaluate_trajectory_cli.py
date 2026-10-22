"""Trace CLI exits distinguish pass, detected failures and insufficient evidence."""
import json
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_trajectory_evaluation import trace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_trajectory.py"


def invoke(tmp_path, events, extra=()):
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events))
    return subprocess.run([sys.executable, "-B", str(SCRIPT), str(path),
        "--max-rounds", "3", "--max-qm-calls", "10", "--max-wall-time", "1000",
        "--target-dataset-size", "10", "--out", str(tmp_path / "report.json"), *extra],
        cwd=tmp_path, capture_output=True, text=True)


def test_cli_pass_and_source_preservation(tmp_path):
    events = trace()
    result = invoke(tmp_path, events)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["overall"] == "pass"
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["metadata"]["source"]["sha256"]
    assert (tmp_path / "trace.jsonl").read_text() == "\n".join(json.dumps(event) for event in events)


def test_cli_fail_and_unknown_exit_codes(tmp_path):
    events = trace(); events[2]["outputs"]["results"].reverse()
    assert invoke(tmp_path, events).returncode == 1
    (tmp_path / "report.json").unlink()
    assert invoke(tmp_path, []).returncode == 3


def test_cli_never_overwrites_inputs_or_reports(tmp_path):
    assert invoke(tmp_path, [], ("--out", str(tmp_path / "trace.jsonl"))).returncode == 2
    (tmp_path / "report.json").write_text("original")
    assert invoke(tmp_path, []).returncode == 2
    assert (tmp_path / "report.json").read_text() == "original"


def test_cli_removes_only_its_new_output_after_write_failure(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("trajectory_cli_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trace_path, output = tmp_path / "trace.jsonl", tmp_path / "report.json"
    trace_path.write_text("")
    original_open = Path.open

    @contextmanager
    def failing_open(path, *args, **kwargs):
        with original_open(path, *args, **kwargs) as handle:
            if path != output:
                yield handle
                return

            class BrokenWriter:
                def write(self, text):
                    handle.write(text[:5])
                    raise OSError("simulated disk write failure")

            yield BrokenWriter()

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(SystemExit) as exc:
        module.main([str(trace_path), "--max-rounds", "3", "--max-qm-calls", "10",
                     "--max-wall-time", "1000", "--target-dataset-size", "10", "--out", str(output)])
    assert exc.value.code == 2
    assert not output.exists()
    assert trace_path.read_bytes() == b""
