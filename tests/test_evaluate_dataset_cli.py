"""Exercise the standalone entry point in a subprocess without chemistry or API keys."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_dataset.py"
METHOD = "dft:B3LYP/def2-SVP"


def invoke(tmp_path, *extra):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), str(tmp_path / "input.jsonl"),
        "--format", "jsonl", "--min", "3", "--max", "3.5", "--qm-method", METHOD,
        "--json-out", str(tmp_path / "report.json"), "--csv-out", str(tmp_path / "report.csv"),
        *extra], cwd=tmp_path, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def test_cli_generates_both_reports_and_preserves_inputs(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(dict(id="a", smiles="CCO", properties={METHOD: 3.25},
        validated=True, provenance=dict(seed="C", parent="CC", generator="test", round="1"))) + "\n")
    evidence = tmp_path / "qm.jsonl"
    evidence.write_text(json.dumps(dict(candidate_id="a", status="ok", value=3.25, method=METHOD)) + "\n")
    original = path.read_bytes(), evidence.read_bytes()
    result = invoke(tmp_path, "--qm-results", str(evidence), "--seed", "C")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["qm_hit_rate"]["value"] == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["metadata"]["qm_results_source"]["sha256"]
    with (tmp_path / "report.csv").open(newline="") as handle:
        assert list(csv.DictReader(handle))[0]["qm_outcome"] == "meets_target"
    assert original == (path.read_bytes(), evidence.read_bytes())


def test_cli_errors_do_not_overwrite_input_or_existing_outputs(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text('{"id":"a","smiles":"CCO"}\n')
    original = path.read_bytes()
    result = invoke(tmp_path, "--json-out", str(path))
    assert result.returncode == 2 and "overwrite inputs" in result.stderr
    assert path.read_bytes() == original
    (tmp_path / "report.csv").write_text("existing")
    result = invoke(tmp_path)
    assert result.returncode == 2 and "new files" in result.stderr
    assert not (tmp_path / "report.json").exists()
    assert (tmp_path / "report.csv").read_text() == "existing"


def test_cli_rejects_bad_target_and_malformed_json(tmp_path):
    (tmp_path / "input.jsonl").write_text('{"id":"a","smiles":"CCO"}\n')
    result = invoke(tmp_path, "--min", "4")
    assert result.returncode == 2
    assert not (tmp_path / "report.json").exists()
    (tmp_path / "input.jsonl").write_text("{bad json}")
    result = invoke(tmp_path)
    assert result.returncode == 2 and "invalid JSON" in result.stderr


def test_cli_collaborator_csv(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("dataset,candidate_id,smiles,qm_method,status,orca_gap_ev\n"
                    f"synthetic,a,CCO,{METHOD},ok,3.25\n"
                    "historical,b,CCN,dft:PBE0/def2-SVP,,3.25\n")
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path), "--format", "csv",
        "--min", "3", "--max", "3.5", "--qm-method", METHOD,
        "--json-out", str(tmp_path / "report.json"), "--csv-out", str(tmp_path / "report.csv")],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["summary"]["rows"] == 2
    assert report["summary"]["qm_coverage"]["value"] == .5
