# Tests for chem/orca.py: argument checks and the tool definition run without ORCA;
# the calculations run real ORCA jobs on water / OH and are skipped when ORCA is missing.
import os
import signal
import sys
from pathlib import Path

import pytest

from molcurator.chem import orca
from molcurator.chem.orca import PROPERTIES, calculate_property, tool_definition
from tests.conftest import needs_mpi, needs_orca

WATER = (["O", "H", "H"], [[0.0, 0.0, 0.1173], [0.0, 0.7572, -0.4692], [0.0, -0.7572, -0.4692]])
OH = (["O", "H"], [[0.0, 0.0, 0.0], [0.0, 0.0, 0.97]])


def _calc(tmp_path, prop, molecule=WATER, **kwargs):
    return calculate_property(*molecule, prop, workdir=tmp_path, **kwargs)


# --- no ORCA needed: everything below fails before a job is written ---

def test_unknown_property_lists_choices(tmp_path):
    r = _calc(tmp_path, "colour")
    assert not r["success"] and "homo_lumo_gap" in r["error"]


def test_input_injection_is_rejected(tmp_path):
    r = _calc(tmp_path, "energy", method="B3LYP\n%pal nprocs 64 end")
    assert not r["success"] and "method" in r["error"]
    assert not any(tmp_path.iterdir())  # nothing was written


def test_geometry_shape_is_checked(tmp_path):
    assert "coordinate" in _calc(tmp_path, "energy", (["O", "H"], [[0, 0, 0]]))["error"]


def test_impossible_multiplicity_fails_early(tmp_path):
    assert "impossible" in _calc(tmp_path, "energy", multiplicity=2)["error"]


def test_spin_requirements(tmp_path):
    assert "closed-shell" in _calc(tmp_path, "s1_t1_gap", OH, multiplicity=2)["error"]
    assert "open-shell" in _calc(tmp_path, "g_tensor")["error"]


def test_xtb_is_not_upgraded_when_upgrades_are_off(tmp_path):
    r = _calc(tmp_path, "s1_t1_gap", method="gfn2-xtb", allow_upgrade=False)
    assert not r["success"] and "needs DFT" in r["error"]


def _fake_mpirun(tmp_path, banner):
    mpirun = tmp_path / banner.split()[-1] / "bin" / "mpirun"
    mpirun.parent.mkdir(parents=True)
    mpirun.write_text(f"#!/bin/sh\necho '{banner}'\n")
    mpirun.chmod(0o755)
    return mpirun


@pytest.mark.parametrize(("banner", "btl"), [("mpirun (Open MPI) 5.0.11", "self,sm"),
                                             ("mpirun (Open MPI) 4.1.6", "self,vader")])
def test_open_mpi_defaults_follow_its_version(tmp_path, banner, btl):
    defaults = orca._mpi_defaults(str(_fake_mpirun(tmp_path, banner)))
    assert defaults == {"OMPI_MCA_pml": "ob1", "OMPI_MCA_osc": "^ucx", "OMPI_MCA_btl": btl}


def test_other_mpi_and_user_settings_are_left_alone(tmp_path, monkeypatch):
    assert orca._mpi_defaults(str(_fake_mpirun(tmp_path, "Intel(R) MPI Library 2021.9"))) == {}
    home = _fake_mpirun(tmp_path / "ompi", "mpirun (Open MPI) 5.0.11").parents[1]
    monkeypatch.setenv("OMPI_MCA_btl", "self,tcp")
    install = orca._orca_install(None, home, 4)
    assert install.openmpi == home and dict(install.extra_env) == {"OMPI_MCA_pml": "ob1", "OMPI_MCA_osc": "^ucx"}
    assert orca._orca_install(None, home, 1).openmpi is None  # serial runs never touch MPI


def test_parallel_run_without_open_mpi_fails_before_any_job(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMPI_HOME", raising=False)
    monkeypatch.setattr(orca.shutil, "which", lambda name: None)
    monkeypatch.setattr(orca, "load_dotenv", lambda: None)  # a developer's .env must not supply one
    r = _calc(tmp_path, "energy", nprocs=4)
    assert not r["success"] and "OPENMPI_HOME" in r["error"]
    assert not any(tmp_path.iterdir())


def test_tool_definition_lists_every_property():
    tool = tool_definition()
    assert tool["input_schema"]["properties"]["property_name"]["enum"] == sorted(PROPERTIES)
    assert set(tool["input_schema"]["required"]) == {"elements", "coordinates", "property_name"}


# --- real ORCA runs (seconds each on water) ---

@needs_orca
def test_xtb_gap_and_dipole(tmp_path):
    gap = _calc(tmp_path, "homo_lumo_gap", method="gfn2-xtb")
    assert gap["success"], gap.get("error")
    assert gap["method"] == "XTB2" and gap["basis"] is None
    assert gap["value"] == pytest.approx(gap["details"]["lumo_ev"] - gap["details"]["homo_ev"])
    dip = _calc(tmp_path, "dipole", method="gfn2-xtb")
    assert dip["success"] and 1.5 < dip["value"] < 3.0  # debye; water is about 1.85


@needs_orca
def test_xtb_is_upgraded_for_tddft(tmp_path):
    r = _calc(tmp_path, "s1_t1_gap", method="gfn2-xtb", nroots=2)
    assert r["success"], r.get("error")
    assert r["method"] == "r2SCAN-3c" and r["notes"]
    assert r["details"]["s1_ev"] > r["details"]["t1_ev"] > 0
    assert r["value"] == pytest.approx(r["details"]["s1_ev"] - r["details"]["t1_ev"])


@needs_orca
def test_dft_frequencies_and_forces(tmp_path):
    freq = _calc(tmp_path, "frequencies", method="HF", basis="6-31G*")
    assert freq["success"], freq.get("error")
    assert len(freq["value"]) == 3 and freq["details"]["n_imaginary"] == 0
    forces = _calc(tmp_path, "forces", method="r2SCAN-3c")
    assert forces["success"] and len(forces["value"]) == 3


@needs_orca
def test_delta_scf_ionization_potential(tmp_path):
    r = _calc(tmp_path, "ionization_potential", method="gfn2-xtb")
    assert r["success"], r.get("error")
    assert r["value"] > 0
    assert set(r["details"]) == {"cation_energy_eh", "neutral_energy_eh"}


@needs_orca
def test_os_environ_survives_orca_runs(tmp_path):
    """OPI's own runner replaces os.environ with a plain dict; ours must not."""
    environ_type = type(os.environ)
    assert _calc(tmp_path, "energy", method="HF", basis="def2-SVP")["success"]
    assert type(os.environ) is environ_type


@needs_orca
@needs_mpi
def test_parallel_run_matches_serial(tmp_path):
    serial = _calc(tmp_path, "homo_lumo_gap", method="PBE0", basis="def2-SVP")
    parallel = _calc(tmp_path, "homo_lumo_gap", method="PBE0", basis="def2-SVP", nprocs=2)
    assert parallel["success"], parallel.get("error")
    assert parallel["value"] == pytest.approx(serial["value"], abs=1e-6)
    assert "nprocs 2" in Path(parallel["workdir"], "main.inp").read_text()
    err = Path(parallel["workdir"], "main.err")
    assert not err.exists() or "UCX" not in err.read_text()


@needs_orca
def test_open_shell_g_tensor(tmp_path):
    r = _calc(tmp_path, "g_tensor", OH, multiplicity=2)
    assert r["success"], r.get("error")
    assert 2.0 < r["value"] < 2.1


@needs_orca
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_timeout_kills_orca_and_its_helpers(tmp_path):
    benzene = (["C"] * 6 + ["H"] * 6,
               [[1.39, 0, 0], [0.695, 1.204, 0], [-0.695, 1.204, 0], [-1.39, 0, 0], [-0.695, -1.204, 0],
                [0.695, -1.204, 0], [2.47, 0, 0], [1.235, 2.139, 0], [-1.235, 2.139, 0], [-2.47, 0, 0],
                [-1.235, -2.139, 0], [1.235, -2.139, 0]])
    r = _calc(tmp_path, "nmr_shielding", benzene, method="PBE0", basis="def2-TZVP", timeout_s=2)
    assert not r["success"] and "TimeoutExpired" in r["error"]
    # No ORCA process (main program or helper) may still be running in the job folder.
    running = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if os.readlink(proc / "cwd") == r["workdir"]:
                running.append(int(proc.name))
        except OSError:
            continue  # exited meanwhile, or not ours to inspect
    for pid in running:
        os.kill(pid, signal.SIGKILL)  # leave the machine clean even when the test fails
    assert not running
