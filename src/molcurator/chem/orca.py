# ORCA property calculations through OPI (orca-pi), shaped as one LLM tool call:
# calculate_property() takes a geometry, a property name and a level of theory, runs the
# ORCA job(s) the property needs, and returns a JSON-serialisable dict.
#
# OPI writes the input, runs ORCA and switches on ORCA's JSON output. Values are read from
# those JSON files directly, not through OPI's typed output models: OPI 2.0's models reject
# several ORCA 6.1.1 property files (TD-DFT with triplets, frequency and SCF timing blocks).
# Three values only appear in the .out file and are read from there: TD-DFT states (state
# labels with multiplicity), and xTB orbital energies and dipole moment.
#
# ORCA binary: ORCA_BIN from the environment / .env, else OPI's own lookup (OPI_ORCA, OPI
# config, `orca` on PATH). Parallel runs (nprocs > 1) need Open MPI: OPENMPI_HOME (the folder
# holding bin/mpirun and lib/, e.g. a conda env), else mpirun on PATH. Parallel runs default
# to single-node shared-memory transport with UCX off (see _mpi_defaults); OMPI_MCA_* values
# already set in the environment win. ORCA processes get an explicit environment; this module
# never changes os.environ (see _runner).
# ORCA starts helper programs (orca_scf, ...); on a timeout the whole process group is
# killed, so no helper keeps running.
import json
import os
import re
import shutil
import signal
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache, cached_property
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from molcurator.chem.properties import (
    AU_TO_DEBYE,
    HARTREE_TO_EV,
    canonical_property,
    check_geometry,
    new_result,
)

DEFAULT_DFT = "r2SCAN-3c"  # used when a property needs an SCF method but xTB was asked for
DEFAULT_BASIS = "def2-SVP"  # used for methods that are not composite (-3c) or semiempirical

# One ORCA keyword token (same rule as tools/validate.py). Tokens go on the "!" line only, and
# whitespace (so newlines) splits them, so a tool argument cannot add input blocks or coordinates.
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+*(),./-]*")
_XTB_ALIASES = {"xtb": "XTB2", "xtb2": "XTB2", "gfn2-xtb": "XTB2", "gfn2": "XTB2",
                "xtb1": "XTB1", "gfn1-xtb": "XTB1", "gfn1": "XTB1"}


@dataclass(frozen=True)
class _Run:
    """One ORCA job of a property workflow, relative to the requested charge and multiplicity."""
    label: str
    charge_shift: int = 0
    multiplicity: int | str | None = None  # None: as requested; "low_spin": lowest for the new charge


@dataclass(frozen=True)
class _Spec:
    description: str
    unit: str
    extract: Callable[["_Job | dict[str, _Job]"], tuple[Any, dict]]
    task: str = "SP"
    needs_scf: bool = False  # True: xTB cannot give it, so xTB requests are moved to DEFAULT_DFT
    keywords: tuple[str, ...] = ()
    blocks: Callable[["_Setup"], list] | None = None
    runs: tuple[_Run, ...] = (_Run("main"),)
    closed_shell_only: bool = False
    open_shell_only: bool = False


@dataclass
class _Setup:
    """Resolved settings shared by every job of one call."""
    method: str
    basis: str | None
    is_xtb: bool
    charge: int
    multiplicity: int
    nroots: int
    extra_keywords: list[str] = field(default_factory=list)


class _Job:
    """Files of one finished ORCA job, read lazily."""

    def __init__(self, folder: Path, basename: str, natoms: int, is_xtb: bool):
        self.folder, self.basename, self.natoms, self.is_xtb = folder, basename, natoms, is_xtb

    def path(self, suffix: str) -> Path:
        return self.folder / f"{self.basename}{suffix}"

    @cached_property
    def out(self) -> str:
        return self.path(".out").read_text(errors="replace")

    @cached_property
    def prop(self) -> dict:
        """Last geometry block of <basename>.property.json (the final one for optimisations)."""
        return json.loads(self.path(".property.json").read_text())["Geometries"][-1]

    @cached_property
    def gbw(self) -> dict:
        return json.loads(self.path(".json").read_text())["Molecule"]

    def scf_energy(self) -> float:
        """Final single-point energy (Eh) of the reference state."""
        return float(self.prop["Single_Point_Data"]["FinalEnergy"])


# ---------------------------------------------------------------------------------------
# Extractors: (job or jobs) -> (value, details)
# ---------------------------------------------------------------------------------------

def _energy(job: _Job):
    return job.scf_energy(), {}


def _gradient_array(job: _Job) -> list[list[float]]:
    """Cartesian gradient (Eh/bohr) from <basename>.engrad, one [x, y, z] row per atom."""
    numbers = [line.strip() for line in job.path(".engrad").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    flat = [float(x) for x in numbers[2:2 + 3 * job.natoms]]  # after the atom count and the energy
    return [flat[i:i + 3] for i in range(0, len(flat), 3)]


def _gradient(job: _Job):
    grad = _gradient_array(job)
    norms = [sum(g * g for g in row) ** 0.5 for row in grad]
    return grad, {"max_atom_norm": max(norms), "energy_eh": job.scf_energy()}


def _forces(job: _Job):
    grad, details = _gradient(job)
    return [[-g for g in row] for row in grad], details


def _optimized_geometry(job: _Job):
    lines = job.path(".xyz").read_text().splitlines()
    atoms = [line.split() for line in lines[2:2 + job.natoms]]
    coords = [[float(x) for x in a[1:4]] for a in atoms]
    converged = "THE OPTIMIZATION HAS CONVERGED" in job.out
    return coords, {"elements": [a[0] for a in atoms], "energy_eh": job.scf_energy(),
                    "converged": converged}


def _thermo(job: _Job) -> dict:
    return job.prop["THERMOCHEMISTRY_Energies"][0]


def _vibrations(job: _Job) -> list[float]:
    """Vibrational wavenumbers (cm-1), without the 5 or 6 translations and rotations;
    imaginary modes come out negative."""
    t = _thermo(job)
    freqs = [f[0] for f in t["FREQ"]]
    return freqs[5 if t["isLinear"] else 6:]


def _frequencies(job: _Job):
    freqs = _vibrations(job)
    return freqs, {"n_imaginary": sum(f < 0 for f in freqs), "zpe_eh": _thermo(job)["zpe"]}


def _thermochemistry(job: _Job):
    t = _thermo(job)
    return t["freeEnergyG"], {
        "temperature_k": t["temperature"], "electronic_energy_eh": t["elEnergy"],
        "zpe_eh": t["zpe"], "inner_energy_eh": t["innerEnergyU"], "enthalpy_eh": t["enthalpyH"],
        "entropy_term_ts_eh": t["entropyS"],
        "n_imaginary": sum(f < 0 for f in _vibrations(job))}


def _frontier_orbitals(job: _Job) -> tuple[float, float]:
    """HOMO and LUMO energies in eV, over both spin channels for open-shell references."""
    if job.is_xtb:  # xTB writes no GBW JSON; its orbital table marks (HOMO) and (LUMO)
        homo = re.findall(r"([-\d.]+)\s+\(HOMO\)", job.out)
        lumo = re.findall(r"([-\d.]+)\s+\(LUMO\)", job.out)
        return float(homo[-1]), float(lumo[-1])
    mos = job.gbw["MolecularOrbitals"]["MOs"]
    occupied = [mo["OrbitalEnergy"] for mo in mos if mo["Occupancy"] > 0]
    virtual = [mo["OrbitalEnergy"] for mo in mos if mo["Occupancy"] == 0]
    return max(occupied) * HARTREE_TO_EV, min(virtual) * HARTREE_TO_EV


def _homo_lumo_gap(job: _Job):
    homo, lumo = _frontier_orbitals(job)
    return lumo - homo, {"homo_ev": homo, "lumo_ev": lumo}


def _dipole(job: _Job):
    if job.is_xtb:  # ORCA switches its own dipole off for xTB; xtb prints one
        vec = re.findall(r"Total Dipole Moment\s*:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", job.out)[-1]
        vector_au = [float(x) for x in vec]
    else:
        vector_au = [row[0] for row in job.prop["Dipole_Moment"][-1]["dipoleTotal"]]
    magnitude_au = sum(x * x for x in vector_au) ** 0.5
    return magnitude_au * AU_TO_DEBYE, {"vector_au": vector_au, "vector_debye": [x * AU_TO_DEBYE for x in vector_au]}


def _charges(key: str):
    def extract(job: _Job):
        block = job.prop[key][-1]
        return [c[0] for c in block["AtomicCharges"]], {}
    return extract


def _polarizability(job: _Job):
    p = job.prop["Polarizability"][-1]
    return p["isotropicPolar"], {"principal_components_au": [x[0] for x in p["diagonalizedTensor"]],
                                 "tensor_au": p["rawCartesian"]}


def _nmr_shielding(job: _Job):
    s = job.prop["Chemical_Shift"][-1]
    shieldings = [{"atom_index": n, "atomic_number": z, "isotropic_ppm": iso, "anisotropy_ppm": aniso}
                  for n, z, iso, aniso in zip(s["NUC"], s["Elems"], s["siso"], s["saniso"])]
    return shieldings, {"note": "absolute shieldings; chemical shift = sigma(reference) - sigma"}


def _g_tensor(job: _Job):
    g = job.prop["G_Tensor"][-1]
    return g["g_iso"], {"principal_values": [x[0] for x in g["g_Tot"]], "delta_g_iso": g["Delta_g_iso"]}


# Rows of ORCA's "ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS" table, e.g.
#   0-1A  ->  1-3A    8.560790   69047.4   144.8   0.000000000 ...
# The final-state label is <root>-<multiplicity><irrep>.
_TRANSITION = re.compile(r"^\s*0-\d+\S*\s+->\s+(\d+)-(\d)\S*\s+([\d.]+)\s+[\d.]+\s+([\d.]+)\s+([\d.eE+-]+)", re.MULTILINE)


def _excited_state_list(job: _Job) -> list[dict]:
    start = job.out.rfind("ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS")
    if start < 0:
        raise ValueError("no TD-DFT absorption table in the ORCA output")
    table = job.out[start:job.out.find("\n\n", start + 400)]
    states = [{"root": int(r), "multiplicity": int(m), "energy_ev": float(e), "wavelength_nm": float(nm),
               "oscillator_strength": float(f)} for r, m, e, nm, f in _TRANSITION.findall(table)]
    if not states:
        raise ValueError("TD-DFT absorption table has no states")
    return sorted(states, key=lambda s: s["energy_ev"])


def _lowest(states: list[dict], multiplicity: int) -> dict:
    found = [s for s in states if s["multiplicity"] == multiplicity]
    if not found:
        raise ValueError(f"no excited states of multiplicity {multiplicity} were computed")
    return found[0]


def _excited_states(job: _Job):
    states = _excited_state_list(job)
    return states, {"n_states": len(states)}


def _s1_energy(job: _Job):
    s1 = _lowest(_excited_state_list(job), 1)
    return s1["energy_ev"], {"oscillator_strength": s1["oscillator_strength"]}


def _t1_energy(job: _Job):
    return _lowest(_excited_state_list(job), 3)["energy_ev"], {}


def _s1_t1_gap(job: _Job):
    states = _excited_state_list(job)
    s1, t1 = _lowest(states, 1)["energy_ev"], _lowest(states, 3)["energy_ev"]
    return s1 - t1, {"s1_ev": s1, "t1_ev": t1}


def _energy_difference(upper: str, lower: str):
    """E(upper) - E(lower) in eV, from two runs of a delta-SCF workflow."""
    def extract(jobs: dict[str, _Job]):
        e_upper, e_lower = jobs[upper].scf_energy(), jobs[lower].scf_energy()
        return (e_upper - e_lower) * HARTREE_TO_EV, {f"{upper}_energy_eh": e_upper, f"{lower}_energy_eh": e_lower}
    return extract


def _tddft_block(setup: _Setup) -> list:
    from opi.input.blocks import BlockTddft
    # Triplets come from a closed-shell reference only; open-shell TD-DFT gives mixed-spin states.
    return [BlockTddft(nroots=setup.nroots, triplets=setup.multiplicity == 1 or None)]


def _polar_block(setup: _Setup) -> list:
    from opi.input.blocks import BlockElprop
    return [BlockElprop(polar="analytic")]


_TDDFT = {"needs_scf": True, "blocks": _tddft_block}

PROPERTIES: dict[str, _Spec] = {
    "energy": _Spec("Total electronic energy (single point).", "Eh", _energy),
    "gradient": _Spec("Cartesian energy gradient, one [x, y, z] row per atom.", "Eh/bohr", _gradient, task="ENGRAD"),
    "forces": _Spec("Cartesian forces (minus the gradient), one row per atom.", "Eh/bohr", _forces, task="ENGRAD"),
    "optimized_geometry": _Spec("Geometry optimisation; final Cartesian coordinates.", "angstrom",
                                _optimized_geometry, task="OPT"),
    "frequencies": _Spec("Harmonic vibrational wavenumbers (negative = imaginary).", "cm^-1",
                         _frequencies, task="FREQ"),
    "thermochemistry": _Spec("Gibbs free energy at 298.15 K and 1 atm, with H, ZPE and TS in details.", "Eh",
                             _thermochemistry, task="FREQ"),
    "homo_lumo_gap": _Spec("HOMO-LUMO gap; HOMO and LUMO energies in details.", "eV", _homo_lumo_gap),
    "dipole_moment": _Spec("Dipole moment magnitude; vector in details.", "debye", _dipole),
    "mulliken_charges": _Spec("Mulliken atomic partial charges.", "e", _charges("Mulliken_Population_Analysis"),
                              needs_scf=True),
    "loewdin_charges": _Spec("Loewdin atomic partial charges.", "e", _charges("Loewdin_Population_Analysis"),
                             needs_scf=True),
    "polarizability": _Spec("Isotropic static dipole polarizability; tensor in details.", "bohr^3",
                            _polarizability, needs_scf=True, blocks=_polar_block),
    "nmr_shielding": _Spec("Isotropic NMR shielding per nucleus.", "ppm", _nmr_shielding,
                           needs_scf=True, keywords=("NMR",)),
    "g_tensor": _Spec("Isotropic EPR g-value (open-shell molecules); principal values in details.", "",
                      _g_tensor, needs_scf=True, keywords=("g-tensor",), open_shell_only=True),
    "excited_states": _Spec("Vertical TD-DFT (TDA) excited states: energy, multiplicity, oscillator strength.",
                            "eV", _excited_states, **_TDDFT),
    "s1_energy": _Spec("Vertical S1 excitation energy (TD-DFT).", "eV", _s1_energy, closed_shell_only=True, **_TDDFT),
    "t1_energy": _Spec("Vertical T1 excitation energy (TD-DFT).", "eV", _t1_energy, closed_shell_only=True, **_TDDFT),
    "s1_t1_gap": _Spec("Singlet-triplet gap Delta E_ST = E(S1) - E(T1) from TD-DFT.", "eV", _s1_t1_gap,
                       closed_shell_only=True, **_TDDFT),
    "s0_t1_gap": _Spec("Vertical delta-SCF gap E(T1) - E(S0): separate singlet and triplet SCF runs. "
                       "Not the S1-T1 gap (use s1_t1_gap).", "eV",
                       _energy_difference("t1", "s0"), closed_shell_only=True, needs_scf=True,
                       runs=(_Run("s0", multiplicity=1), _Run("t1", multiplicity=3))),
    "ionization_potential": _Spec("Vertical ionisation potential E(cation) - E(neutral), delta-SCF.", "eV",
                                  _energy_difference("cation", "neutral"),
                                  runs=(_Run("neutral"), _Run("cation", charge_shift=1, multiplicity="low_spin"))),
    "electron_affinity": _Spec("Vertical electron affinity E(neutral) - E(anion), delta-SCF.", "eV",
                               _energy_difference("neutral", "anion"),
                               runs=(_Run("neutral"), _Run("anion", charge_shift=-1, multiplicity="low_spin"))),
}


# ---------------------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------------------

def _tokens(text: str, what: str) -> list[str]:
    tokens = text.split()
    bad = [t for t in tokens if not _TOKEN.fullmatch(t)]
    if not tokens or bad:
        raise ValueError(f"{what} must be ORCA keyword tokens, got {text!r}")
    return tokens


def _resolve_method(method: str, basis: str | None, spec: _Spec, notes: list[str],
                    allow_upgrade: bool) -> tuple[str, str | None, bool]:
    """ORCA method keyword(s), basis set (None if the method fixes its own) and whether it is xTB."""
    method = " ".join(_tokens(method, "method"))
    xtb = _XTB_ALIASES.get(method.strip().lower())
    if xtb and spec.needs_scf and not allow_upgrade:
        raise ValueError(f"{method} cannot give this property; it needs DFT or HF")
    if xtb and spec.needs_scf:
        notes.append(f"{method} cannot give this property; ran {DEFAULT_DFT} instead.")
        return DEFAULT_DFT, None, False
    if xtb:
        if basis:
            notes.append(f"Basis set {basis} ignored: xTB has its own minimal basis.")
        return xtb, None, True
    if method.split()[0].lower().endswith("-3c"):  # composite methods (r2SCAN-3c, B97-3c, HF-3c) fix the basis
        if basis:
            notes.append(f"Basis set {basis} ignored: {method} is a composite method with its own basis.")
        return method, None, False
    if not basis:
        notes.append(f"No basis set given; used {DEFAULT_BASIS}.")
    return method, basis or DEFAULT_BASIS, False


@cache
def _mpi_defaults(mpirun: str) -> dict[str, str]:
    """Open MPI settings for a single-node ORCA run. UCX (the default network layer of
    Open MPI 5) fails under WSL and on most workstations, flooding the .err file and slowing
    the run, so it is switched off; processes talk through shared memory, which Open MPI 5
    calls "sm" and Open MPI 4 "vader". Measured on naphthalene, PBE0/def2-TZVP, 4 cores:
    20-28 s with these settings, 33-36 s with Open MPI's defaults, 60 s on 1 core."""
    version = subprocess.run([mpirun, "--version"], capture_output=True, text=True, timeout=30, check=False).stdout
    if "Open MPI" not in version and "OpenRTE" not in version:
        return {}  # another MPI: leave its settings alone
    major = re.search(r"(\d+)\.\d+", version)
    shared_memory = "vader" if major and int(major.group(1)) < 5 else "sm"
    return {"OMPI_MCA_pml": "ob1", "OMPI_MCA_osc": "^ucx", "OMPI_MCA_btl": f"self,{shared_memory}"}


def _find_mpirun(openmpi_home: str | None) -> str:
    if openmpi_home:
        mpirun = Path(openmpi_home).expanduser() / "bin" / "mpirun"
        if not os.access(mpirun, os.X_OK):
            raise ValueError(f"OPENMPI_HOME={openmpi_home} has no executable bin/mpirun")
        return str(mpirun)
    if mpirun := shutil.which("mpirun"):
        return mpirun
    raise ValueError("nprocs > 1 needs Open MPI: set OPENMPI_HOME (the folder holding bin/mpirun, e.g. a "
                     "conda env with openmpi) in .env, put mpirun on PATH, or use nprocs=1")


@dataclass(frozen=True)
class _OrcaInstall:
    """Where ORCA and Open MPI live, and extra environment for the ORCA processes."""
    orca: Path | None  # ORCA_BIN; None: OPI's own lookup (OPI_ORCA, OPI config, `orca` on PATH)
    openmpi: Path | None  # OPENMPI_HOME; None: mpirun on PATH, or a serial run
    extra_env: tuple[tuple[str, str], ...] = ()


def _orca_install(orca_bin: str | os.PathLike | None, openmpi_home: str | os.PathLike | None,
                  nprocs: int) -> _OrcaInstall:
    load_dotenv()  # fills in from .env; variables already set in the shell win
    orca = orca_bin or os.environ.get("ORCA_BIN")
    if nprocs == 1:
        return _OrcaInstall(Path(orca) if orca else None, None)
    home = str(openmpi_home or os.environ.get("OPENMPI_HOME") or "") or None
    defaults = _mpi_defaults(_find_mpirun(home))
    extra = tuple((k, v) for k, v in defaults.items() if k not in os.environ)  # the user's own OMPI_MCA_* win
    return _OrcaInstall(Path(orca) if orca else None, Path(home).expanduser() if home else None, extra)


def _orca_error(job: _Job) -> str:
    """Short reason for a failed ORCA run: first line of <basename>.err (e.g. "mpirun: not
    found"), else the first ERROR line of the output."""
    err = job.path(".err")
    lines = err.read_text(errors="replace").splitlines() if err.exists() else []
    if not lines and job.path(".out").exists():
        lines = [line for line in job.out.splitlines() if "ERROR" in line and "error termination" not in line]
    lines = [line.strip() for line in lines if line.strip()]
    return lines[0] if lines else "ORCA did not terminate normally"


# ORCA starts helper programs (orca_scf, mpirun, ...); each run gets its own process group
# (POSIX) or process tree (Windows), so a timeout can stop all of them.
_NEW_PROCESS_GROUP = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                      else {"start_new_session": True})


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":  # no process groups to signal: taskkill /T ends the whole child tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def _runner(install: _OrcaInstall, working_dir: Path):
    """OPI's Runner (it finds ORCA's bin/ and lib/ and Open MPI) with its own run():

    - ORCA starts in its own process group, and a timeout or interrupt kills the whole
      group (OPI's run() kills only the main orca process, leaving helpers like orca_scf);
    - each ORCA process gets an explicit environment. OPI's run() instead edits os.environ
      and then replaces it with a plain dict, after which no environment change in this
      Python process reaches any child process.
    """
    from opi.execution.core import Runner
    from opi.utils.misc import add_to_env

    class GroupKillingRunner(Runner):
        def __init__(self) -> None:
            super().__init__(working_dir)

        def set_orca_path(self, orca_path=None, /):
            super().set_orca_path(orca_path or install.orca)

        def set_open_mpi_path(self, mpi_path=None, /):
            super().set_open_mpi_path(mpi_path or install.openmpi)

        def _environment(self) -> dict[str, str]:
            env = dict(os.environ)
            add_to_env("PATH", str(self._orca_bin_folder), prepend=True, env=env)
            add_to_env("LD_LIBRARY_PATH", str(self._orca_lib_folder), prepend=True, env=env)
            if self._open_mpi_path:
                add_to_env("PATH", str(self._open_mpi_path / "bin"), prepend=True, env=env)
                add_to_env("LD_LIBRARY_PATH", str(self._open_mpi_path / "lib"), prepend=True, env=env)
            env.update(install.extra_env)
            return env

        def run(self, binary, args=(), /, *, stdin_str=None, stdout=None, stderr=None, silent=True,
                capture=False, cwd=None, timeout=-1):
            command = [str(self.get_orca_binary(binary)), *args]
            limit = timeout if timeout > 0 else None
            if capture:  # short calls such as `orca --version`
                return subprocess.run(command, input=stdin_str, capture_output=True, text=True, check=False,
                                      cwd=cwd or self.working_dir, env=self._environment(), timeout=limit)
            with open(stdout or os.devnull, "w") as out, open(stderr or os.devnull, "w") as err:
                proc = subprocess.Popen(command, stdout=out, stderr=err, cwd=cwd or self.working_dir,
                                        env=self._environment(), **_NEW_PROCESS_GROUP)
                try:
                    proc.wait(timeout=limit)
                except BaseException:  # timeout or interrupt: stop ORCA and every helper it started
                    _kill_tree(proc)
                    raise
            return None

    return GroupKillingRunner()


@cache
def _check_version(install: _OrcaInstall) -> None:
    """OPI's ORCA version check (ORCA 6.1.1 or newer), once per installation and process."""
    _runner(install, Path.cwd()).check_version()


def _run_job(run: _Run, spec: _Spec, setup: _Setup, elements: list[str], coordinates: list,
             folder: Path, install: _OrcaInstall, nprocs: int, maxcore_mb: int, timeout_s: int) -> _Job:
    from opi.core import Calculator
    from opi.input.structures.structure import Structure

    structure = Structure.from_lists(elements, [tuple(map(float, c)) for c in coordinates],
                                     charge=setup.charge + run.charge_shift)
    if run.multiplicity == "low_spin":
        structure.set_ls_multiplicity()
    else:
        structure.multiplicity = run.multiplicity or setup.multiplicity
    if not structure.multiplicity_is_possible:
        raise ValueError(f"multiplicity {structure.multiplicity} is impossible for charge "
                         f"{structure.charge} ({structure.nelectrons} electrons)")

    calc = Calculator(basename=run.label, working_dir=folder, version_check=False)  # see _check_version
    calc.structure = structure
    keywords = [*setup.method.split(), *(setup.basis.split() if setup.basis else []), spec.task,
                *spec.keywords, *setup.extra_keywords]
    calc.input.add_simple_keywords(*keywords)
    if spec.blocks:
        calc.input.add_blocks(*spec.blocks(setup))
    calc.input.ncores = nprocs
    calc.input.memory = maxcore_mb
    calc.write_input()
    _runner(install, folder).run_orca(calc.inpfile, timeout=timeout_s)

    job = _Job(folder, run.label, len(elements), setup.is_xtb)
    if not calc.get_output().terminated_normally():
        raise RuntimeError(f"ORCA run '{run.label}' failed: {_orca_error(job)} (see {job.path('.out')})")
    return job


def calculate_property(
    elements: list[str],
    coordinates: list[list[float]],
    property_name: str,
    method: str = DEFAULT_DFT,
    basis: str | None = None,
    charge: int = 0,
    multiplicity: int = 1,
    extra_keywords: list[str] | None = None,
    nroots: int = 5,
    workdir: str | os.PathLike = "orca_jobs",
    nprocs: int = 1,
    maxcore_mb: int = 2000,
    timeout_s: int | None = None,
    orca_bin: str | os.PathLike | None = None,
    openmpi_home: str | os.PathLike | None = None,
    allow_upgrade: bool = True,
) -> dict[str, Any]:
    """Compute one molecular property with ORCA at the requested level of theory.

    elements: element symbols, e.g. ["O", "H", "H"]; coordinates: Cartesian positions in
    angstrom, one [x, y, z] per atom. property_name: a key of PROPERTIES (or ALIASES).
    method: an ORCA method keyword ("r2SCAN-3c", "B3LYP", "PBE0 D4", "HF", ...) or an xTB
    name ("gfn2-xtb", "xtb", "gfn1-xtb"). Properties that need an SCF wavefunction
    (polarizability, NMR, TD-DFT, ...) are run with r2SCAN-3c when xTB is asked for and the
    result's notes say so; with allow_upgrade=False they fail instead. extra_keywords:
    further ORCA simple keywords, e.g. ["TightSCF", "CPCM(water)"]. nroots: TD-DFT roots per
    multiplicity. nprocs > 1 runs ORCA in parallel through Open MPI (openmpi_home, else
    OPENMPI_HOME, else mpirun on PATH).

    Each call runs in a new folder under workdir. Never raises: failures come back as
    {"success": False, "error": ...}. Values are vertical (at the given geometry) unless the
    property is optimized_geometry.
    """
    key = canonical_property(property_name)
    result = new_result(key, method)
    notes: list[str] = []
    try:
        if key not in PROPERTIES:
            raise ValueError(f"unknown property {property_name!r}; choose from {sorted(PROPERTIES)}")
        spec = PROPERTIES[key]
        check_geometry(elements, coordinates)
        if spec.closed_shell_only and multiplicity != 1:
            raise ValueError(f"{key} needs a closed-shell singlet reference (multiplicity 1)")
        if spec.open_shell_only and multiplicity == 1:
            raise ValueError(f"{key} needs an open-shell molecule (multiplicity > 1)")
        if not 1 <= nroots <= 50:
            raise ValueError("nroots must be between 1 and 50")

        orca_method, orca_basis, is_xtb = _resolve_method(method, basis, spec, notes, allow_upgrade)
        if orca_basis:
            _tokens(orca_basis, "basis")
        extra = [t for kw in (extra_keywords or []) for t in _tokens(kw, "extra_keywords")]
        setup = _Setup(orca_method, orca_basis, is_xtb, charge, multiplicity, nroots, extra)
        result.update(method=orca_method, basis=orca_basis)

        install = _orca_install(orca_bin, openmpi_home, nprocs)  # fails before any folder is made
        _check_version(install)
        folder = Path(workdir).resolve() / f"{key}-{uuid.uuid4().hex[:8]}"
        folder.mkdir(parents=True)
        result["workdir"] = str(folder)
        timeout = timeout_s or int(os.environ.get("MOLCURATOR_QC_TIMEOUT_S", "600"))

        jobs = {run.label: _run_job(run, spec, setup, elements, coordinates, folder, install,
                                    nprocs, maxcore_mb, timeout) for run in spec.runs}
        value, details = spec.extract(jobs if len(spec.runs) > 1 else jobs[spec.runs[0].label])
        result.update(success=True, value=value, unit=spec.unit, details=details)
    except Exception as exc:  # noqa: BLE001 - the tool reports failures to its caller instead of raising
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["notes"] = notes
    return result


def tool_definition(name: str = "orca_calculate_property") -> dict[str, Any]:
    """Tool definition (Anthropic tool-use format: name, description, input_schema) for
    calculate_property, exposing the chemistry arguments and leaving runtime settings
    (workdir, nprocs, memory, timeout, ORCA path) to the caller."""
    listing = "\n".join(f"- {k} [{s.unit or 'dimensionless'}]: {s.description}" for k, s in PROPERTIES.items())
    return {
        "name": name,
        "description": (
            "Run an ORCA quantum-chemistry calculation for one molecular property at a chosen level of "
            "theory and return its value. Values are vertical (at the given geometry) unless the property "
            "is optimized_geometry. Properties that need an SCF wavefunction are moved from xTB to "
            f"{DEFAULT_DFT} automatically, and the result's notes say so.\n\nProperties:\n{listing}"),
        "input_schema": {
            "type": "object",
            "properties": {
                "elements": {"type": "array", "items": {"type": "string"},
                             "description": "Element symbols, one per atom, e.g. [\"O\", \"H\", \"H\"]."},
                "coordinates": {"type": "array",
                                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                                "description": "Cartesian coordinates in angstrom, one [x, y, z] per atom."},
                "property_name": {"type": "string", "enum": sorted(PROPERTIES)},
                "method": {"type": "string",
                           "description": f"ORCA method keyword, e.g. {DEFAULT_DFT}, B3LYP, PBE0, wB97X-D3, HF, "
                                          "or gfn2-xtb. Default " + DEFAULT_DFT + "."},
                "basis": {"type": "string",
                          "description": f"Basis set, e.g. def2-SVP, def2-TZVP. Ignored for -3c and xTB methods; "
                                         f"default {DEFAULT_BASIS} otherwise."},
                "charge": {"type": "integer", "description": "Total molecular charge. Default 0."},
                "multiplicity": {"type": "integer", "minimum": 1, "description": "Spin multiplicity 2S+1. Default 1."},
                "extra_keywords": {"type": "array", "items": {"type": "string"},
                                   "description": "Extra ORCA simple keywords, e.g. [\"D4\", \"TightSCF\", \"CPCM(water)\"]."},
                "nroots": {"type": "integer", "minimum": 1, "maximum": 50,
                           "description": "TD-DFT roots per multiplicity (excited-state properties). Default 5."},
            },
            "required": ["elements", "coordinates", "property_name"],
        },
    }
