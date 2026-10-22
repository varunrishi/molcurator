# xTB property calculations through tblite's Python API, shaped as one LLM tool call:
# calculate_property() takes a geometry, a property name and an xTB method, and returns the
# same JSON-serialisable dict as chem/orca.py. No external binary: tblite is a pip package.
#
# xTB is a ground-state method. Excited states (S1, T1, the S1-T1 gap), NMR, EPR and
# polarizabilities are not available from any xTB Python interface; those requests fail
# with a pointer to chem/orca.py (TD-DFT / DFT).
#
# Geometry optimisation uses SciPy's L-BFGS-B on the xTB energy; frequencies come from a
# central-difference Hessian of analytic gradients, with translations and rotations
# projected out. Open-shell molecules use tblite's spin-summed orbitals (fractional
# occupations), so HOMO/LUMO there mean highest partly occupied / lowest empty.
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from molcurator.chem.properties import (
    AU_TO_DEBYE,
    BOHR_TO_ANGSTROM,
    HARTREE_PER_WAVENUMBER,
    HARTREE_TO_EV,
    canonical_property,
    check_geometry,
    new_result,
)

METHODS = {"gfn2-xtb": "GFN2-xTB", "gfn2": "GFN2-xTB", "xtb": "GFN2-xTB", "xtb2": "GFN2-xTB",
           "gfn1-xtb": "GFN1-xTB", "gfn1": "GFN1-xTB", "xtb1": "GFN1-xTB",
           "ipea1-xtb": "IPEA1-xTB", "ipea1": "IPEA1-xTB", "ipea-xtb": "IPEA1-xTB"}
DEFAULT_METHOD = "gfn2-xtb"

# Harmonic wavenumber (cm^-1) per sqrt(Eh / (bohr^2 amu)).
_WAVENUMBER_PER_AU = 5140.486777
_FD_STEP_BOHR = 0.005
_ORCA_ONLY = {"excited_states", "s1_energy", "t1_energy", "s1_t1_gap", "s0_t1_gap", "polarizability",
              "nmr_shielding", "g_tensor", "loewdin_charges", "thermochemistry"}


def is_xtb(method: str) -> bool:
    return method.strip().lower() in METHODS


@dataclass
class _Molecule:
    numbers: np.ndarray
    positions: np.ndarray  # bohr
    charge: int
    uhf: int  # unpaired electrons = multiplicity - 1
    method: str  # tblite name, e.g. "GFN2-xTB"
    solvent: str | None

    def singlepoint(self, positions: np.ndarray | None = None, charge: int | None = None, uhf: int | None = None):
        from tblite.interface import Calculator
        calc = Calculator(self.method, self.numbers, self.positions if positions is None else positions,
                          charge=float(self.charge if charge is None else charge), uhf=self.uhf if uhf is None else uhf)
        calc.set("verbosity", 0)
        if self.solvent:
            calc.add("alpb-solvation", self.solvent)
        return calc.singlepoint()


@dataclass(frozen=True)
class _Spec:
    description: str
    unit: str
    extract: Callable[[_Molecule], tuple[Any, dict]]


def _energy(mol: _Molecule):
    return float(mol.singlepoint().get("energy")), {}


def _gradient(mol: _Molecule):
    res = mol.singlepoint()
    grad = res.get("gradient")
    return grad.tolist(), {"max_atom_norm": float(np.linalg.norm(grad, axis=1).max()),
                           "energy_eh": float(res.get("energy"))}


def _forces(mol: _Molecule):
    grad, details = _gradient(mol)
    return (-np.asarray(grad)).tolist(), details


def _frontier(mol: _Molecule):
    res = mol.singlepoint()
    energies, occupations = res.get("orbital-energies"), res.get("orbital-occupations")
    homo = energies[occupations > 1e-6].max() * HARTREE_TO_EV
    lumo = energies[occupations < 1e-6].min() * HARTREE_TO_EV
    return float(lumo - homo), {"homo_ev": float(homo), "lumo_ev": float(lumo)}


def _dipole(mol: _Molecule):
    vector = mol.singlepoint().get("dipole")
    return float(np.linalg.norm(vector) * AU_TO_DEBYE), {"vector_au": vector.tolist(),
                                                        "vector_debye": (vector * AU_TO_DEBYE).tolist()}


def _quadrupole(mol: _Molecule):
    xx, xy, yy, xz, yz, zz = mol.singlepoint().get("quadrupole")  # traceless, packed lower triangle
    tensor = [[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]
    return tensor, {"note": "traceless quadrupole tensor, atomic units"}


def _charges(mol: _Molecule):
    return mol.singlepoint().get("charges").tolist(), {}


def _bond_orders(mol: _Molecule):
    wbo = mol.singlepoint().get("bond-orders")
    wbo = wbo.sum(axis=2) if wbo.ndim == 3 else wbo  # spin channels summed
    n = len(mol.numbers)
    bonds = [{"atoms": [i, j], "order": float(wbo[i, j])} for i in range(n) for j in range(i + 1, n) if wbo[i, j] > 0.1]
    return bonds, {"note": "Wiberg-Mayer bond orders above 0.1"}


def _low_spin_uhf(mol: _Molecule, charge: int) -> int:
    return int((mol.numbers.sum() - charge) % 2)


def _ionization_potential(mol: _Molecule):
    e0 = float(mol.singlepoint().get("energy"))
    e1 = float(mol.singlepoint(charge=mol.charge + 1, uhf=_low_spin_uhf(mol, mol.charge + 1)).get("energy"))
    return (e1 - e0) * HARTREE_TO_EV, {"neutral_energy_eh": e0, "cation_energy_eh": e1}


def _electron_affinity(mol: _Molecule):
    e0 = float(mol.singlepoint().get("energy"))
    e1 = float(mol.singlepoint(charge=mol.charge - 1, uhf=_low_spin_uhf(mol, mol.charge - 1)).get("energy"))
    return (e0 - e1) * HARTREE_TO_EV, {"neutral_energy_eh": e0, "anion_energy_eh": e1}


def _optimize(mol: _Molecule) -> tuple[np.ndarray, float, bool, int]:
    from scipy.optimize import minimize

    def energy_and_gradient(flat):
        res = mol.singlepoint(positions=flat.reshape(-1, 3))
        return float(res.get("energy")), res.get("gradient").ravel()

    opt = minimize(energy_and_gradient, mol.positions.ravel(), jac=True, method="L-BFGS-B",
                   options={"gtol": 3e-4, "maxiter": 1000})  # gtol: max gradient component, Eh/bohr
    return opt.x.reshape(-1, 3), float(opt.fun), bool(opt.success), int(opt.nit)


def _optimized_geometry(mol: _Molecule):
    positions, energy, converged, steps = _optimize(mol)
    return (positions * BOHR_TO_ANGSTROM).tolist(), {"energy_eh": energy, "converged": converged, "steps": steps}


def _frequencies(mol: _Molecule):
    """Harmonic wavenumbers at the given geometry (not re-optimised: run optimized_geometry
    first for a minimum). Negative values are imaginary modes."""
    from rdkit import Chem
    n = len(mol.numbers)
    hessian = np.zeros((3 * n, 3 * n))
    for k in range(3 * n):
        step = np.zeros(3 * n)
        step[k] = _FD_STEP_BOHR
        plus = mol.singlepoint(positions=(mol.positions.ravel() + step).reshape(-1, 3)).get("gradient").ravel()
        minus = mol.singlepoint(positions=(mol.positions.ravel() - step).reshape(-1, 3)).get("gradient").ravel()
        hessian[k] = (plus - minus) / (2 * _FD_STEP_BOHR)
    hessian = (hessian + hessian.T) / 2
    table = Chem.GetPeriodicTable()
    masses = np.array([table.GetAtomicWeight(int(z)) for z in mol.numbers])
    sqrt_m = np.repeat(np.sqrt(masses), 3)
    weighted = hessian / np.outer(sqrt_m, sqrt_m)
    # Project out translations and rotations (in mass-weighted coordinates).
    centre = (masses[:, None] * mol.positions).sum(axis=0) / masses.sum()
    r = mol.positions - centre
    vectors = [np.tile(np.eye(3)[a], n) * sqrt_m for a in range(3)]
    vectors += [np.cross(np.eye(3)[a], r).ravel() * sqrt_m for a in range(3)]
    basis, singular, _ = np.linalg.svd(np.array(vectors).T, full_matrices=False)
    basis = basis[:, singular > 1e-6 * singular.max()]  # 5 vectors for a linear molecule
    projector = np.eye(3 * n) - basis @ basis.T
    eigenvalues = np.linalg.eigvalsh(projector @ weighted @ projector)
    eigenvalues = np.delete(eigenvalues, np.argsort(np.abs(eigenvalues))[:basis.shape[1]])
    wavenumbers = np.sign(eigenvalues) * np.sqrt(np.abs(eigenvalues)) * _WAVENUMBER_PER_AU
    zpe = 0.5 * wavenumbers[wavenumbers > 0].sum() * HARTREE_PER_WAVENUMBER
    return sorted(wavenumbers.tolist()), {"n_imaginary": int((wavenumbers < 0).sum()), "zpe_eh": float(zpe)}


PROPERTIES: dict[str, _Spec] = {
    "energy": _Spec("Total xTB energy (single point).", "Eh", _energy),
    "gradient": _Spec("Cartesian energy gradient, one [x, y, z] row per atom.", "Eh/bohr", _gradient),
    "forces": _Spec("Cartesian forces (minus the gradient), one row per atom.", "Eh/bohr", _forces),
    "optimized_geometry": _Spec("Geometry optimisation (L-BFGS-B); final Cartesian coordinates.", "angstrom",
                                _optimized_geometry),
    "frequencies": _Spec("Harmonic vibrational wavenumbers at the given geometry (negative = imaginary).",
                         "cm^-1", _frequencies),
    "homo_lumo_gap": _Spec("HOMO-LUMO gap; HOMO and LUMO energies in details.", "eV", _frontier),
    "dipole_moment": _Spec("Dipole moment magnitude; vector in details.", "debye", _dipole),
    "quadrupole_moment": _Spec("Traceless quadrupole tensor.", "e*bohr^2", _quadrupole),
    "mulliken_charges": _Spec("Atomic partial charges (Mulliken, xTB).", "e", _charges),
    "bond_orders": _Spec("Wiberg-Mayer bond orders of bonded atom pairs.", "", _bond_orders),
    "ionization_potential": _Spec("Vertical E(cation) - E(neutral), delta-SCF. No empirical correction: "
                                  "xTB overestimates IPs by several eV, so use for trends only.", "eV",
                                  _ionization_potential),
    "electron_affinity": _Spec("Vertical E(neutral) - E(anion), delta-SCF. No empirical correction; "
                               "trends only.", "eV", _electron_affinity),
}


def calculate_property(
    elements: list[str],
    coordinates: list[list[float]],
    property_name: str,
    method: str = DEFAULT_METHOD,
    charge: int = 0,
    multiplicity: int = 1,
    solvent: str | None = None,
) -> dict[str, Any]:
    """Compute one molecular property with xTB (tblite) at the given geometry.

    elements: element symbols; coordinates: angstrom, one [x, y, z] per atom. property_name:
    a key of PROPERTIES (or an alias). method: gfn2-xtb (default), gfn1-xtb or ipea1-xtb.
    solvent: an ALPB solvent name such as "water" or "toluene"; None is gas phase.

    Never raises: failures come back as {"success": False, "error": ...}. Values are vertical
    (at the given geometry) unless the property is optimized_geometry.
    """
    key = canonical_property(property_name)
    result = new_result(key, method)
    try:
        if key in _ORCA_ONLY:
            raise ValueError(f"xTB cannot give {key}; use molcurator.chem.orca (DFT / TD-DFT)")
        if key not in PROPERTIES:
            raise ValueError(f"unknown property {property_name!r}; choose from {sorted(PROPERTIES)}")
        if not is_xtb(method):
            raise ValueError(f"unknown xTB method {method!r}; choose from gfn2-xtb, gfn1-xtb, ipea1-xtb")
        check_geometry(elements, coordinates)
        if multiplicity < 1:
            raise ValueError("multiplicity must be at least 1")
        from rdkit import Chem
        table = Chem.GetPeriodicTable()
        numbers = np.array([table.GetAtomicNumber(e) for e in elements])
        if (numbers.sum() - charge - (multiplicity - 1)) % 2:
            raise ValueError(f"multiplicity {multiplicity} is impossible for charge {charge} "
                             f"({numbers.sum() - charge} electrons)")
        mol = _Molecule(numbers, np.asarray(coordinates, dtype=float) / BOHR_TO_ANGSTROM, charge,
                        multiplicity - 1, METHODS[method.strip().lower()], solvent)
        spec = PROPERTIES[key]
        value, details = spec.extract(mol)
        result.update(success=True, method=mol.method, basis=None, value=value, unit=spec.unit, details=details)
    except Exception as exc:  # noqa: BLE001 - the tool reports failures to its caller instead of raising
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["notes"] = []
    return result


def tool_definition(name: str = "xtb_calculate_property") -> dict[str, Any]:
    """Tool definition (Anthropic tool-use format) for calculate_property."""
    listing = "\n".join(f"- {k} [{s.unit or 'dimensionless'}]: {s.description}" for k, s in PROPERTIES.items())
    return {
        "name": name,
        "description": ("Run a fast semiempirical xTB calculation (tblite) for one ground-state molecular property "
                        "and return its value. Seconds per molecule; less accurate than DFT. Excited states, NMR, "
                        f"EPR and polarizabilities need the ORCA tool instead.\n\nProperties:\n{listing}"),
        "input_schema": {
            "type": "object",
            "properties": {
                "elements": {"type": "array", "items": {"type": "string"},
                             "description": "Element symbols, one per atom, e.g. [\"O\", \"H\", \"H\"]."},
                "coordinates": {"type": "array",
                                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                                "description": "Cartesian coordinates in angstrom, one [x, y, z] per atom."},
                "property_name": {"type": "string", "enum": sorted(PROPERTIES)},
                "method": {"type": "string", "enum": ["gfn2-xtb", "gfn1-xtb", "ipea1-xtb"],
                           "description": "xTB parametrisation. Default gfn2-xtb."},
                "charge": {"type": "integer", "description": "Total molecular charge. Default 0."},
                "multiplicity": {"type": "integer", "minimum": 1, "description": "Spin multiplicity 2S+1. Default 1."},
                "solvent": {"type": "string", "description": "ALPB implicit solvent, e.g. water, toluene. Omit for gas phase."},
            },
            "required": ["elements", "coordinates", "property_name"],
        },
    }
