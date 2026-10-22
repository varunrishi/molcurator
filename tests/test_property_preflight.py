"""Preflight (scripts/check_property_tools.py) reports availability without starting calculations."""
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_property_tools",
                                              Path(__file__).resolve().parents[1] / "scripts/check_property_tools.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_env_file_fills_only_chemistry_settings_and_keeps_overrides(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('ORCA_BIN="/from/file/orca"\nANTHROPIC_API_KEY=not-exported\nMOLCURATOR_QC_TIMEOUT_S=42\n')
    monkeypatch.setenv("ORCA_BIN", "/existing/orca")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MOLCURATOR_QC_TIMEOUT_S", raising=False)
    check._env(path)
    assert os.environ["ORCA_BIN"] == "/existing/orca"
    assert os.environ["MOLCURATOR_QC_TIMEOUT_S"] == "42"
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_orca_path_is_checked_without_launch(tmp_path, monkeypatch):
    exe = tmp_path / "fake-orca"
    exe.write_text("fixture")
    exe.chmod(0o755)
    monkeypatch.setenv("ORCA_BIN", str(exe))
    report = check.preflight("all", tmp_path / "absent.env")
    assert report["ok"] and not report["runtime_tested"]
    assert {c["name"] for c in report["checks"]} >= {"xTB engine", "opi", "ORCA_BIN"}


def test_xtb_only_preflight_needs_no_orca(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCA_BIN", str(tmp_path / "missing"))
    assert check.preflight("xtb", tmp_path / "absent.env")["ok"]


def test_missing_orca_fails_with_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCA_BIN", str(tmp_path / "missing"))
    report = check.preflight("orca", tmp_path / "absent.env")
    assert not report["ok"]
    assert "Set ORCA_BIN" in next(c for c in report["checks"] if c["name"] == "ORCA_BIN")["detail"]


def test_parallel_settings_without_open_mpi_fail(tmp_path, monkeypatch):
    exe = tmp_path / "fake-orca"
    exe.write_text("fixture")
    exe.chmod(0o755)
    config = tmp_path / "chem.json"
    config.write_text('{"orca_nprocs": 4}')
    monkeypatch.setenv("ORCA_BIN", str(exe))
    monkeypatch.setenv("MOLCURATOR_CHEM_CONFIG", str(config))
    monkeypatch.setenv("OPENMPI_HOME", str(tmp_path / "no-mpi"))
    report = check.preflight("orca", tmp_path / "absent.env")
    mpi = next(c for c in report["checks"] if c["name"] == "Open MPI")
    assert not report["ok"] and not mpi["ok"] and "bin/mpirun" in mpi["detail"]


def test_cli_json_no_smoke_by_default(monkeypatch, capsys):
    monkeypatch.setattr(check, "preflight", lambda *a: {"ok": True, "checks": [], "runtime_tested": False})
    monkeypatch.setattr(check, "smoke", lambda *a: (_ for _ in ()).throw(AssertionError("must not calculate")))
    monkeypatch.setattr("sys.argv", ["check_property_tools.py", "--json"])
    assert check.main() == 0
    assert not json.loads(capsys.readouterr().out)["runtime_tested"]


def test_runtime_smoke_failure_returns_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check, "preflight", lambda *a: {"ok": True, "checks": [], "runtime_tested": False})
    monkeypatch.setattr(check, "smoke", lambda *a: {"ok": False, "calculations_recorded": 1})
    monkeypatch.setattr("sys.argv", ["check_property_tools.py", "--json", "--smoke", "--out", str(tmp_path / "run")])
    assert check.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["runtime_tested"] and not report["ok"]


def test_missing_tblite_falls_back_to_orca_or_fails(tmp_path, monkeypatch):
    from molcurator.chem import backends
    monkeypatch.setattr(backends, "tblite_error", lambda: "ModuleNotFoundError: No module named 'tblite'")
    monkeypatch.setenv("ORCA_BIN", str(tmp_path / "missing"))
    check_xtb = next(c for c in check.preflight("xtb", tmp_path / "absent.env")["checks"] if c["name"] == "xTB engine")
    assert not check_xtb["ok"] and "no ORCA" in check_xtb["detail"]
    exe = tmp_path / "fake-orca"
    exe.write_text("fixture")
    exe.chmod(0o755)
    monkeypatch.setenv("ORCA_BIN", str(exe))
    check_xtb = next(c for c in check.preflight("xtb", tmp_path / "absent.env")["checks"] if c["name"] == "xTB engine")
    assert check_xtb["ok"] and "built-in xTB" in check_xtb["detail"]
