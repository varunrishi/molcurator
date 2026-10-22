# Shared vocabulary of the property tools (chem/orca.py, chem/xtb.py): unit conversions,
# property-name normalisation and the result dict both return.
from typing import Any

HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANGSTROM = 0.529177210903
AU_TO_DEBYE = 2.541746473
HARTREE_PER_WAVENUMBER = 4.556335252912e-6  # Eh per cm^-1

# Common alternative spellings an LLM or a user may send.
ALIASES = {"dipole": "dipole_moment", "hl_gap": "homo_lumo_gap", "gap": "homo_lumo_gap",
           "freq": "frequencies", "opt": "optimized_geometry", "geometry": "optimized_geometry",
           "polarisability": "polarizability", "nmr": "nmr_shielding", "epr": "g_tensor",
           "tddft": "excited_states", "delta_est": "s1_t1_gap", "dest": "s1_t1_gap", "ip": "ionization_potential",
           "ea": "electron_affinity", "free_energy": "thermochemistry", "charges": "mulliken_charges",
           "quadrupole": "quadrupole_moment", "wbo": "bond_orders"}


def canonical_property(name: str) -> str:
    """Lower-case, underscore-separated property key with aliases resolved."""
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(key, key)


def new_result(key: str, method: str) -> dict[str, Any]:
    """Starting result dict; calculate_property fills in value/unit/details or error."""
    return {"success": False, "property": key, "requested_method": method}


def check_geometry(elements: list[str], coordinates: list) -> None:
    if len(elements) != len(coordinates) or not elements:
        raise ValueError(f"{len(elements)} elements but {len(coordinates)} coordinate rows")
    if any(len(row) != 3 for row in coordinates):
        raise ValueError("each coordinate row must be [x, y, z] in angstrom")

# Properties with one number per molecule: the only ones a run or batch can target.
SCALAR_PROPERTIES = ("energy", "homo_lumo_gap", "dipole_moment", "polarizability", "g_tensor", "s1_energy",
                     "t1_energy", "s1_t1_gap", "s0_t1_gap", "ionization_potential", "electron_affinity",
                     "thermochemistry")
