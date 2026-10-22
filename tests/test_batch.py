# Tests for the molcurator-properties batch command (molcurator/batch): input checks,
# checkpointed resume, QM selection, reports, plots and SLURM scripts. The chemistry tools
# are replaced, so nothing here launches a calculation.
import csv
import json
import shlex
from types import SimpleNamespace

import pytest

from molcurator.batch import cli, reporting, slurm
from molcurator.chem.settings import active_settings, load_settings
from molcurator.schemas import Prediction, QMResult, Status


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "generated.csv"
    path.write_text("id,smiles,parent_smiles,round,generator\ngood,CCO,CC,2,test\nbad,invalid,CC,2,test\n")
    return path


@pytest.fixture
def tools(monkeypatch):
    calls = []

    def predict(candidates, target, directory, method=None, basis=None):
        candidate = candidates[0]
        calls.append(("predict", candidate.id, method) + ((basis,) if basis else ()))
        if candidate.smiles == "invalid":
            return [Prediction(candidate_id=candidate.id, status=Status.failed, error="invalid SMILES")]
        directory.mkdir(exist_ok=True, parents=True)
        path = directory / (candidate.id + ".xyz")
        path.write_text("2\ncharge=0 multiplicity=1\nH 0 0 0\nH 0 0 .74\n")
        return [Prediction(candidate_id=candidate.id, status=Status.ok, value=3.25, xyz_path=path)]

    def validate(items, target, qm):
        calls.append(("qm", items[0].candidate_id, qm.functional))
        return [QMResult(candidate_id=items[0].candidate_id, status=Status.ok, value=4.0,
                         method=f"dft:{qm.functional}/{qm.basis}")]

    monkeypatch.setattr(cli, "predict", predict)
    monkeypatch.setattr(cli, "validate", validate)
    return calls


def test_csv_mixed_batch_reports_and_resume(tmp_path, source, tools):
    out = tmp_path / "run"
    arguments = ["run", str(source), "--out", str(out), "--orca", "--no-plots"]
    assert cli.main(arguments) == 1
    state = json.loads((out / "results.json").read_text())
    assert state["run_status"] == "completed_with_failures"
    assert [r["candidate"]["id"] for r in state["rows"]] == ["good", "bad"]
    assert state["rows"][0]["qm_result"]["value"] == 4
    assert state["rows"][1]["qm_selection"] == "prediction_failed"
    assert tools == [("predict", "good", "gfn2-xtb"), ("qm", "good", "B3LYP"), ("predict", "bad", "gfn2-xtb")]
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert rows[1]["predict_value"] == "" and rows[1]["predict_error"] == "invalid SMILES"
    assert rows[0]["parent_smiles"] == "CC" and rows[0]["round"] == "2" and rows[0]["property"] == "homo_lumo_gap"
    assert json.loads((out / "csv_schema.json").read_text())["units"]["qm_value"] == "eV"
    assert cli.main(arguments + ["--resume"]) == 1
    assert len(list((out / "history").glob("*.json"))) == 1
    assert active_settings.get() is None
    assert cli.main(arguments) == 2  # no silent overwrite


def test_property_and_methods_reach_the_tools(tmp_path, source, tools):
    args = ["run", str(source), "--out", str(tmp_path / "run"), "--property", "s1_t1_gap", "--max", "0.3",
            "--orca", "--functional", "PBE0", "--no-plots"]
    cli.main(args)
    assert tools[0] == ("predict", "good", "B97-3c")  # TD-DFT default: xTB cannot give S1-T1
    assert all(call[0] == "predict" for call in tools)  # 3.25 eV is outside the window
    state = json.loads((tmp_path / "run/results.json").read_text())
    assert state["target"] == {"name": "s1_t1_gap", "units": "eV", "min": None, "max": 0.3}
    assert cli.main(["run", str(source), "--out", str(tmp_path / "r2"), "--property", "frequencies"]) == 2


def test_xtb_validation_method_is_refused_before_execution(tmp_path, source, tools, capsys):
    args = ["run", str(source), "--out", str(tmp_path / "run"), "--orca", "--functional", "gfn2-xtb"]
    assert cli.main(args) == 2
    assert tools == [] and "--functional is 'gfn2-xtb'" in capsys.readouterr().err


def test_predict_level_options_reach_predict_and_are_checked(tmp_path, source, tools, capsys):
    args = ["run", str(source), "--out", str(tmp_path / "run"), "--predict-method", "PBE0", "--predict-basis",
            "def2-TZVP", "--no-plots"]
    cli.main(args)
    assert tools[0] == ("predict", "good", "PBE0", "def2-TZVP")
    assert "PREDICT method: PBE0/def2-TZVP" in (tmp_path / "run/report.md").read_text()
    bad = ["run", str(source), "--out", str(tmp_path / "r2"), "--predict-method", "gfn2-xtb", "--predict-basis", "x"]
    assert cli.main(bad) == 2 and "--predict-basis 'x' would be ignored" in capsys.readouterr().err
    same = ["run", str(source), "--out", str(tmp_path / "r3"), "--orca", "--predict-method", "B3LYP"]
    assert cli.main(same) == 2 and "VALIDATE must use a higher level" in capsys.readouterr().err
    assert len(tools) == 2 and not (tmp_path / "r2").exists()


def test_changed_resume_input_is_rejected(tmp_path, source, tools):
    args = ["run", str(source), "--out", str(tmp_path / "run"), "--no-plots"]
    cli.main(args)
    source.write_text("id,smiles\nnew,CC\n")
    assert cli.main(args + ["--resume"]) == 2
    assert len(tools) == 2


@pytest.mark.parametrize("text", ["id,smiles\na,CC\na,CCC\n", "smiles\nCC\n",
    "id,smiles\na,\n", "id,smiles\n../bad,CC\n", "id,smiles\na,CC,extra\n", "id,smiles\n"])
def test_invalid_input_is_rejected_before_execution(tmp_path, text, tools):
    path = tmp_path / "input.csv"
    path.write_text(text)
    assert cli.main(["run", str(path), "--out", str(tmp_path / "run"), "--no-plots"]) == 2
    assert tools == []
    assert not (tmp_path / "run").exists()


def test_smiles_input_ids_and_comments(tmp_path):
    path = tmp_path / "molecules.smi"
    path.write_text("# comment\nCCO ethanol\n\nCCCC\n")
    rows = cli.read_candidates(path)
    assert [r.id for r in rows] == ["ethanol", "mol000002"]
    assert rows[1].smiles == "CCCC"


def test_qm_limit_and_window_are_explicit(tmp_path, tools):
    path = tmp_path / "input.smi"
    path.write_text("CC a\nCCC b\n")
    args = ["run", str(path), "--out", str(tmp_path / "run"), "--orca", "--orca-limit", "1", "--no-plots"]
    assert cli.main(args) == 0
    assert [c[:2] for c in tools] == [("predict", "a"), ("qm", "a"), ("predict", "b")]
    state = json.loads((tmp_path / "run/results.json").read_text())
    assert state["rows"][1]["qm_selection"] == "limit_reached"
    assert cli.main(args + ["--resume", "--min-gap", "4"]) == 0  # old option name still works
    state = json.loads((tmp_path / "run/results.json").read_text())
    assert all(row["qm_selection"] == "outside_window" for row in state["rows"])


def test_interruption_keeps_checkpoint_and_releases_lock(tmp_path, source, tools, monkeypatch):
    original = cli.predict

    def interrupted(candidates, target, directory, method=None, basis=None):
        if candidates[0].id == "bad":
            raise KeyboardInterrupt
        return original(candidates, target, directory, method, basis)

    monkeypatch.setattr(cli, "predict", interrupted)
    args = ["run", str(source), "--out", str(tmp_path / "run"), "--no-plots"]
    assert cli.main(args) == 130
    state = json.loads((tmp_path / "run/results.json").read_text())
    assert state["run_status"] == "interrupted" and state["rows"][0]["prediction"]["status"] == "ok"
    assert state["rows"][1]["prediction"] is None
    monkeypatch.setattr(cli, "predict", original)
    assert cli.main(args + ["--resume"]) == 1


def test_lock_excludes_another_writer(tmp_path):
    with cli.run_lock(tmp_path), pytest.raises(ValueError, match="another batch"), cli.run_lock(tmp_path):
        pytest.fail("second writer admitted")


def test_plots_and_report_only_do_not_run_chemistry(tmp_path, source, tools, monkeypatch):
    pytest.importorskip("matplotlib")
    out = tmp_path / "run"
    cli.main(["run", str(source), "--out", str(out), "--no-plots"])
    monkeypatch.setattr(cli, "predict", lambda *a, **k: pytest.fail("report must not calculate"))
    assert cli.main(["report", str(out), "--plots"]) == 0
    for name in ("values.png", "execution.png", "conformers.png", "status.png"):
        assert (out / "plots" / name).stat().st_size > 1000
    assert "Calculation history" in (out / "report.md").read_text()


def test_all_failed_batch_still_has_plots(tmp_path, tools):
    pytest.importorskip("matplotlib")
    path = tmp_path / "fail.csv"
    path.write_text("id,smiles\na,invalid\n")
    assert cli.main(["run", str(path), "--out", str(tmp_path / "run"), "--plots"]) == 1
    assert (tmp_path / "run/plots/values.png").is_file()


def test_cluster_resources_checked_before_chemistry(tmp_path, source, tools, monkeypatch):
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "1")
    config = tmp_path / "chem.json"
    config.write_text('{"orca_nprocs": 4}')
    monkeypatch.setenv("MOLCURATOR_CHEM_CONFIG", str(config))
    assert cli.main(["run", str(source), "--out", str(tmp_path / "run"), "--orca", "--no-plots"]) == 2
    assert tools == []


def test_orca_memory_allocation_guard(tmp_path, source, tools, monkeypatch):
    monkeypatch.setenv("SLURM_MEM_PER_NODE", "1000")
    assert cli.main(["run", str(source), "--out", str(tmp_path / "run"), "--orca", "--no-plots"]) == 2
    assert tools == []


def test_settings_are_frozen_for_batch_invocation(tmp_path, source, tools, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"nconfs": 4}')
    monkeypatch.setenv("MOLCURATOR_CHEM_CONFIG", str(settings))
    seen = []
    original = cli.predict

    def edited_configuration(*args, **kwargs):
        seen.append(load_settings().nconfs)
        settings.write_text('{"nconfs": 8}')
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "predict", edited_configuration)
    cli.main(["run", str(source), "--out", str(tmp_path / "run"), "--no-plots"])
    assert seen == [4, 4]
    assert load_settings().nconfs == 8  # changes apply after the invocation


def test_missing_plot_dependencies_fail_before_chemistry(tmp_path, source, tools, monkeypatch):
    def missing():
        raise ImportError("install reports extra")
    monkeypatch.setattr(reporting, "require_plotting", missing)
    assert cli.main(["run", str(source), "--out", str(tmp_path / "run"), "--plots"]) == 2
    assert tools == []


def test_plotting_is_opt_in_without_importing_plot_backend(tmp_path, source, tools, monkeypatch):
    def forbidden():
        pytest.fail("default report must not load plotting")
    monkeypatch.setattr(reporting, "require_plotting", forbidden)
    out = tmp_path / "run"
    assert cli.main(["run", str(source), "--out", str(out)]) == 1
    assert (out / "summary.csv").exists() and not (out / "plots").exists()
    assert cli.main(["report", str(out)]) == 0
    assert "## Figures" not in (out / "report.md").read_text()


@pytest.mark.parametrize("settings", [{"partition": "short\n#SBATCH --nodes=99"},
    {"modules": ["gcc; evil"]}, {"project_dir": "relative"}, {"time": "25:99:00"},
    {"cpus_per_task": 0}, {"memory_mb": 0}, {"functional": "B3LYP; rm"}, {"xtb_bin": "/opt/xtb"}])
def test_invalid_slurm_configuration_rejected(settings):
    values = {"project_dir": "/home/user/project", "input": "/work/input.csv", "out": "/work/results"}
    values.update(settings)
    with pytest.raises(ValueError):
        slurm.SlurmSettings(**values)


def test_slurm_quotes_paths_and_passes_the_property():
    config = slurm.SlurmSettings(project_dir="/home/user/my project", input="/work/input's.csv",
                                 out="/work/results", orca=True, orca_limit=3, modules=["gcc/12", "openmpi/4"],
                                 cpus_per_task=4, chemistry_config="/work/chemistry.json", resume=True,
                                 property="s1_t1_gap", max_value=0.3, functional="PBE0",
                                 predict_method="PBE0", predict_basis="def2-SVP")
    script = slurm.render(config)
    assert "#SBATCH --cpus-per-task=4" in script
    assert "cd -- '/home/user/my project'" in script
    command = shlex.split(script.strip().splitlines()[-1])
    assert command[:3] == ["/home/user/my project/.venv/bin/python", "-m", "molcurator.batch.cli"]
    assert "/work/input's.csv" in command and "--resume" in command and "--orca" in command
    assert command[command.index("--property") + 1] == "s1_t1_gap" and command[command.index("--max") + 1] == "0.3"
    assert command[command.index("--predict-basis") + 1] == "def2-SVP"
    assert "module load gcc/12 openmpi/4" in script


def test_slurm_does_not_submit_by_default_and_records_explicit_submission(tmp_path, monkeypatch):
    config = tmp_path / "slurm.json"
    config.write_text(json.dumps({"project_dir": "/home/user/project", "input": "/work/input.csv", "out": "/work/run"}))
    monkeypatch.setattr(slurm.subprocess, "run", lambda *a, **k: pytest.fail("must not submit"))
    assert slurm.prepare(config, tmp_path / "first.sbatch") == 0
    assert b"\r\n" not in (tmp_path / "first.sbatch").read_bytes()
    monkeypatch.setattr(slurm.shutil, "which", lambda value: "/usr/bin/sbatch")
    submitted = []

    def submit(args, **kwargs):
        submitted.append(args)
        return SimpleNamespace(stdout="12345;cluster\n")

    monkeypatch.setattr(slurm.subprocess, "run", submit)
    assert slurm.prepare(config, tmp_path / "second.sbatch", submit=True) == 0
    assert submitted[0][1] == "--parsable"
    assert json.loads((tmp_path / "second.sbatch.submission.json").read_text())["job_id"] == "12345;cluster"


def test_slurm_module_initialization_is_quoted():
    config = slurm.SlurmSettings(project_dir="/home/project", input="/work/input.csv", out="/work/run",
                                 module_init="/etc/profile.d/modules.sh", modules=["gcc/12"])
    text = slurm.render(config)
    assert text.index("source /etc/profile.d/modules.sh") < text.index("module load gcc/12")


def test_slurm_plotting_defaults_off_and_explicit_on():
    values = {"project_dir": "/home/user/project", "input": "/work/input.csv", "out": "/work/run"}
    assert "--plots" not in slurm.render(slurm.SlurmSettings(**values))
    assert "--plots" in slurm.render(slurm.SlurmSettings(**values, plots=True))
