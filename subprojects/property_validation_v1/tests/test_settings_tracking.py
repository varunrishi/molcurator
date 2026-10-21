import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from molcurator_property_validation.chem import tracking
from molcurator_property_validation.chem.calculations import run, xtb_gap
from molcurator_property_validation.chem.geometry import lowest_ff_conformer
from molcurator_property_validation.chem.settings import ChemistrySettings, load_settings
from molcurator.schemas import Prediction, PropertyTarget, QMSettings, Status


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("MOLCURATOR_CHEM_CONFIG", raising=False)
    monkeypatch.delenv("MOLCURATOR_QC_TIMEOUT_S", raising=False)


def config(tmp_path, monkeypatch, **values):
    path = tmp_path / "chemistry.json"
    path.write_text(json.dumps(values))
    monkeypatch.setenv("MOLCURATOR_CHEM_CONFIG", str(path))
    return path


@pytest.mark.parametrize("values", [dict(nconfs=0), dict(random_seed=-1),
    dict(mmff_max_iterations=0), dict(mmff_force_tolerance=0),
    dict(mmff_energy_tolerance=float("inf")), dict(temperature_k=float("nan")),
    dict(orca_nprocs=0), dict(orca_maxcore_mb=0), dict(timeout_s=-1),
    dict(unknown_option=1), dict(nconfs=True), dict(cache_enabled="false")])
def test_invalid_settings_rejected(values):
    with pytest.raises(ValueError):
        ChemistrySettings(**values)


def test_configuration_changes_real_geometry_and_timeout(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, nconfs=4, random_seed=17, mmff_max_iterations=800,
           mmff_force_tolerance=0.0002, mmff_energy_tolerance=0.00001,
           temperature_k=320, rms_cutoff_angstrom=0.3, timeout_s=900)
    _, report = lowest_ff_conformer("CCCC")
    assert report["n_embedded"] == 4
    assert report["random_seed"] == 17
    assert report["temperature_k"] == 320
    assert report["mmff_max_iterations"] == 800
    assert report["mmff_force_tolerance"] == 0.0002
    assert report["mmff_energy_tolerance"] == 0.00001
    assert report["rms_cutoff_angstrom"] == 0.3
    assert load_settings().timeout_s == 900
    monkeypatch.setenv("MOLCURATOR_QC_TIMEOUT_S", "45")
    assert load_settings().timeout_s == 45


def invoke(tmp_path, monkeypatch, script=None, settings=None, context=None):
    monkeypatch.setenv("XTB_BIN", sys.executable)
    return tracking.calculate(tmp_path / "xtb", "xtb", ["program.py"],
        {"program.py": (script or "print('xtb version 6.7.1')\nprint('HOMO-LUMO GAP 3.25 eV')\nprint('normal termination of xtb')\n").encode()},
        xtb_gap, run, settings or ChemistrySettings(),
        context or dict(candidate_id="test", smiles="CCO"))


def latest(tmp_path):
    return json.loads((tmp_path / "xtb/attempt.json").read_text())


def test_real_process_cache_reuse_and_changed_settings(tmp_path, monkeypatch):
    assert invoke(tmp_path, monkeypatch) == 3.25
    first = latest(tmp_path)
    assert first["process_started"] and first["electronic_calls_attempted"] == 1
    assert first["runtime_s"] > 0 and first["program_version"] == "6.7.1"
    assert first["recipe"]["executable"]["sha256"]
    assert invoke(tmp_path, monkeypatch) == 3.25
    second = latest(tmp_path)
    assert second["cache_hit"] and second["electronic_calls_attempted"] == 0
    assert second["reused_attempt_id"] == first["attempt_id"]
    invoke(tmp_path, monkeypatch, settings=ChemistrySettings(nconfs=31))
    assert not latest(tmp_path)["cache_hit"]
    records = list((tmp_path / "xtb/attempts").glob("*/attempt.json"))
    assert len(records) == 3
    assert sum(json.loads(p.read_text())["electronic_calls_attempted"] for p in records) == 2


def test_corrupted_or_interrupted_output_never_reused(tmp_path, monkeypatch):
    invoke(tmp_path, monkeypatch)
    first = latest(tmp_path)
    source = tmp_path / "xtb/attempts" / first["attempt_id"]
    (source / "xtb.out").write_text("truncated")
    invoke(tmp_path, monkeypatch)
    assert not latest(tmp_path)["cache_hit"]
    good = latest(tmp_path)
    record = tmp_path / "xtb/attempts" / good["attempt_id"] / "attempt.json"
    payload = json.loads(record.read_text()); payload["status"] = "started"
    record.write_text(json.dumps(payload))
    invoke(tmp_path, monkeypatch)
    assert not latest(tmp_path)["cache_hit"]


def test_input_and_executable_change_invalidate_cache(tmp_path, monkeypatch):
    invoke(tmp_path, monkeypatch)
    invoke(tmp_path, monkeypatch, context=dict(candidate_id="test", smiles="CCCC"))
    assert not latest(tmp_path)["cache_hit"]
    original = tracking.executable_identity
    def changed(*args):
        identity = original(*args)
        return dict(identity, sha256="changed-binary")
    monkeypatch.setattr(tracking, "executable_identity", changed)
    invoke(tmp_path, monkeypatch)
    assert not latest(tmp_path)["cache_hit"]


def test_timeout_recorded_and_retryable(tmp_path, monkeypatch):
    with pytest.raises(subprocess.TimeoutExpired):
        invoke(tmp_path, monkeypatch, script="import time; time.sleep(10)",
               settings=ChemistrySettings(timeout_s=0.05))
    record = latest(tmp_path)
    assert record["timed_out"] and record["status"] == "failed"
    assert record["electronic_calls_attempted"] == 1
    assert not (tmp_path / "xtb/cache.json").exists()
    assert invoke(tmp_path, monkeypatch) == 3.25


def test_failed_output_counted_and_cache_disabled(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        invoke(tmp_path, monkeypatch, script="print('invalid chemistry output')")
    assert latest(tmp_path)["electronic_calls_attempted"] == 1
    assert latest(tmp_path)["version_status"] == "not_reported"
    invoke(tmp_path, monkeypatch, settings=ChemistrySettings(cache_enabled=False))
    invoke(tmp_path, monkeypatch, settings=ChemistrySettings(cache_enabled=False))
    assert not latest(tmp_path)["cache_hit"]
    assert not (tmp_path / "xtb/cache.json").exists()


def test_missing_binary_has_zero_process_launches(tmp_path, monkeypatch):
    monkeypatch.setenv("XTB_BIN", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        tracking.calculate(tmp_path / "xtb", "xtb", ["initial.xyz"],
            {"initial.xyz": b"geometry"}, xtb_gap, run, ChemistrySettings(),
            dict(candidate_id="missing"))
    record = latest(tmp_path)
    assert record["status"] == "failed"
    assert not record["process_started"] and record["electronic_calls_attempted"] == 0


def test_configured_orca_resources_reach_input(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, orca_nprocs=4, orca_maxcore_mb=1500)
    module = importlib.import_module("molcurator_property_validation.tools.validate")
    xyz = tmp_path / "mol.xyz"
    xyz.write_text("2\ntest\nH 0 0 0\nH 0 0 .74\n")
    def fake_run(key, backend, args, cwd, log):
        text = (cwd / "gap.inp").read_text()
        assert "%pal nprocs 4 end" in text and "%maxcore 1500" in text
        log.write_text("Program Version 6.1.1\nSCF CONVERGED AFTER 3 CYCLES\nORBITAL ENERGIES\n 0 2.0 -.2 -5\n 1 0.0 -.1 -2\n\nORCA TERMINATED NORMALLY\n")
    monkeypatch.setattr(module, "run", fake_run)
    result = module.validate([Prediction(candidate_id="mol", status=Status.ok, value=2, xyz_path=xyz)],
        PropertyTarget(name="homo_lumo_gap", min=0), QMSettings())[0]
    assert result.status is Status.ok and result.value == 3
    record = json.loads((tmp_path / "calculations/mol/orca/attempt.json").read_text())
    assert record["program_version"] == "6.1.1"
    assert record["recipe"]["settings"]["orca_nprocs"] == 4


def test_summary_counts_launches_not_cache_events(tmp_path, monkeypatch):
    from molcurator_property_validation.chem.summary import summarize
    invoke(tmp_path, monkeypatch)
    invoke(tmp_path, monkeypatch)
    interrupted = tmp_path / "orca/attempts/interrupted"
    interrupted.mkdir(parents=True)
    (interrupted / "attempt.json").write_text(json.dumps(dict(
        status="started", backend="orca", electronic_calls_attempted=0)))
    (interrupted / "process.json").write_text(json.dumps(dict(
        electronic_calls_attempted=1, process_started=True)))
    report = summarize(tmp_path)
    assert report["events"] == 3 and report["cache_hits"] == 1
    assert report["electronic_calls_attempted"] == 2
    assert report["by_backend"] == dict(xtb=1, orca=1)
    assert report["running_or_interrupted"] == 1


def test_changed_input_and_cache_epoch_trigger_new_process(tmp_path, monkeypatch):
    invoke(tmp_path, monkeypatch)
    invoke(tmp_path, monkeypatch, script="print('HOMO-LUMO GAP 4.0 eV'); print('normal termination of xtb')")
    assert latest(tmp_path)["value"] == 4.0 and not latest(tmp_path)["cache_hit"]
    invoke(tmp_path, monkeypatch, settings=ChemistrySettings(cache_epoch="new-runtime"))
    assert not latest(tmp_path)["cache_hit"]


def test_backend_input_mutation_fails_and_never_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("XTB_BIN", sys.executable)
    def mutate(key, backend, args, cwd, log):
        (cwd / "initial.xyz").write_bytes(b"modified geometry")
        log.write_text("HOMO-LUMO GAP 3 eV\nnormal termination of xtb")
    with pytest.raises(ValueError, match="changed a single-point input"):
        tracking.calculate(tmp_path / "xtb", "xtb", [], {"initial.xyz": b"original geometry"},
            xtb_gap, mutate, ChemistrySettings(), dict(candidate_id="mutation"))
    assert latest(tmp_path)["status"] == "failed"
    assert not (tmp_path / "xtb/cache.json").exists()


def test_nonzero_exit_is_counted_and_keeps_log(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="exited with code 2"):
        invoke(tmp_path, monkeypatch, script="import sys; print('xtb version 6.7.1'); sys.exit(2)")
    record = latest(tmp_path)
    assert record["returncode"] == 2 and record["electronic_calls_attempted"] == 1
    assert record["program_version"] == "6.7.1"


def test_corrupted_manifest_is_recomputed(tmp_path, monkeypatch):
    invoke(tmp_path, monkeypatch)
    (tmp_path / "xtb/cache.json").write_text("{truncated")
    invoke(tmp_path, monkeypatch)
    assert not latest(tmp_path)["cache_hit"]


def test_public_smoke_resume_reuses_both_backends(tmp_path, monkeypatch):
    import importlib.util
    script = Path(__file__).resolve().parents[3] / "scripts/check_property_tools.py"
    spec = importlib.util.spec_from_file_location("restart_smoke_check", script)
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    config(tmp_path, monkeypatch, nconfs=3)
    monkeypatch.setenv("XTB_BIN", sys.executable)
    monkeypatch.setenv("ORCA_BIN", sys.executable)
    predict_module = importlib.import_module("molcurator_property_validation.tools.predict")
    validate_module = importlib.import_module("molcurator_property_validation.tools.validate")
    def controlled_process(key, backend, args, cwd, log):
        output = ("xtb version 6.7.1\nHOMO-LUMO GAP 3.25 eV\nnormal termination of xtb\n"
                  if backend == "xtb" else
                  "Program Version 6.1.1\nSCF CONVERGED AFTER 3 CYCLES\nORBITAL ENERGIES\n 0 2.0 -.2 -5\n 1 0.0 -.1 -2\n\nORCA TERMINATED NORMALLY\n")
        (cwd / "controlled.py").write_text("print(" + repr(output) + ")")
        run(key, backend, ["controlled.py"], cwd, log)
    monkeypatch.setattr(predict_module, "run", controlled_process)
    monkeypatch.setattr(validate_module, "run", controlled_process)
    out = tmp_path / "run"
    first = check.smoke("all", out)
    assert first["ok"] and first["electronic_calls_attempted"] == 2, first
    second = check.smoke("all", out, resume=True)
    assert second["ok"] and second["cache_hits"] == 2
    assert second["electronic_calls_attempted"] == 0
    from molcurator_property_validation.chem.summary import summarize
    assert summarize(out)["by_backend"] == dict(xtb=1, orca=1)

    # A changed functional must not reuse an earlier ORCA result.
    from molcurator.tools.validate import validate
    pred = Prediction.model_validate(second["predictions"][0])
    result = validate([pred], PropertyTarget(name="homo_lumo_gap", min=0),
                      QMSettings(functional="PBE0"))[0]
    assert result.status is Status.ok
    assert summarize(out)["by_backend"] == dict(xtb=1, orca=2)
