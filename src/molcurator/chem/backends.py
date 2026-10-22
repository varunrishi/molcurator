# One entry point over the two property tools: xTB methods run in-process through tblite
# (chem/xtb.py), everything else through ORCA (chem/orca.py). PREDICT and VALIDATE call
# this, so both record what ran the same way.
#
# Fallback: where tblite cannot be imported (no wheel for the platform, e.g. Windows via pip),
# GFN2-/GFN1-xTB run through ORCA's built-in xTB instead, which gives the same numbers; the
# result's notes say so. This covers a missing tblite only: a failed xTB calculation is
# reported as failed, never re-run on ORCA.
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from molcurator.chem import orca, xtb
from molcurator.chem.properties import SCALAR_PROPERTIES, canonical_property
from molcurator.chem.settings import ChemistrySettings

# xTB methods ORCA can run itself (GFN2/GFN1); IPEA1-xTB has no ORCA equivalent.
_ORCA_XTB = {"GFN2-xTB": "gfn2-xtb", "GFN1-xTB": "gfn1-xtb"}
_ORCA_XTB_NAMES = {"XTB2": "GFN2-xTB", "XTB1": "GFN1-xTB"}  # ORCA keyword -> method name


@cache
def tblite_error() -> str | None:
    """None if tblite imports, else why not (checked once per process)."""
    try:
        import tblite.interface  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - any import failure means: use the fallback
        return f"{type(exc).__name__}: {exc}"
    return None


def backend_for(method: str) -> str:
    """"xtb" (tblite) or "orca"; xTB methods go to ORCA when tblite is unavailable."""
    if not xtb.is_xtb(method):
        return "orca"
    return "xtb" if tblite_error() is None else "orca"


# Accepted spellings of each tool unit, compared case-insensitively.
_UNIT_SPELLINGS = {"ev": {"ev"}, "debye": {"debye", "d"}, "eh": {"eh", "hartree", "ha", "au", "a.u."},
                   "bohr^3": {"bohr^3", "bohr**3", "bohr3", "au", "a.u."}, "": {"", "dimensionless", "none", "-"}}


def check_target(name: str, units: str | None) -> str:
    """The units for a run or batch target, after checking that name is a single-number property
    the tools compute. units None: the property's own unit. A unit that does not match the
    property is refused, since the target window must be in the unit the tools return."""
    if name not in SCALAR_PROPERTIES:
        hint = canonical_property(name)
        suggestion = f" Did you mean {hint!r}?" if hint != name and hint in SCALAR_PROPERTIES else ""
        raise ValueError(f"target {name!r} is not a single-number property the tools compute.{suggestion} "
                         f"Choose from: {', '.join(SCALAR_PROPERTIES)}")
    unit = orca.PROPERTIES[name].unit
    if units is None:
        return unit
    if units.strip().lower() in _UNIT_SPELLINGS.get(unit.lower(), {unit.lower()}):
        return units
    raise ValueError(f"target units {units!r} do not match {name}, which the tools compute in "
                     f"{unit or 'no unit (dimensionless)'}: give the window in {unit or 'plain numbers'} "
                     "and set units to that, or leave units out to use it")


def xtb_validation_message(method: str) -> str | None:
    """Warning for an xTB method in VALIDATE, else None. VALIDATE is the higher level of
    theory that checks PREDICT, whose default for most targets is GFN2-xTB."""
    if not xtb.is_xtb(method):
        return None
    return (f"qm.functional is {method!r}, an xTB method. PREDICT runs GFN2-xTB wherever xTB can give the "
            "target, so VALIDATE needs a different, higher-level method to check it: set qm.functional to a "
            "DFT method (e.g. B3LYP, PBE0 or r2SCAN-3c) with a basis set.")


def calculate_property(elements: list[str], coordinates: list[list[float]], property_name: str, method: str,
                       basis: str | None, charge: int, multiplicity: int, workdir: Path,
                       settings: ChemistrySettings, extra_keywords: list[str] | None = None) -> dict[str, Any]:
    """Result dict of the matching tool, plus backend, timing and timestamps.

    Never upgrades the method: a property the method cannot give fails, so a pipeline step
    never runs a far more expensive calculation than its config asked for.
    """
    def run_orca(orca_method: str) -> dict[str, Any]:
        return orca.calculate_property(elements, coordinates, property_name, method=orca_method, basis=basis,
                                       charge=charge, multiplicity=multiplicity, extra_keywords=extra_keywords,
                                       workdir=workdir, nprocs=settings.orca_nprocs,
                                       maxcore_mb=settings.orca_maxcore_mb, timeout_s=int(settings.timeout_s),
                                       allow_upgrade=False)

    backend = backend_for(method)
    started, clock = datetime.now(UTC).isoformat(), time.monotonic()
    if backend == "xtb":
        result = xtb.calculate_property(elements, coordinates, property_name, method=method,
                                        charge=charge, multiplicity=multiplicity)
    elif xtb.is_xtb(method):  # tblite unavailable: ORCA's built-in xTB
        name = xtb.METHODS[method.strip().lower()]
        if name in _ORCA_XTB:
            result = run_orca(_ORCA_XTB[name])
            note = f"tblite is not available ({tblite_error()}); ran {name} through ORCA's built-in xTB."
            result["notes"] = [note, *result["notes"]]
        else:
            result = {"success": False, "property": property_name, "requested_method": method, "notes": [],
                      "error": f"{name} needs tblite, which is not available ({tblite_error()}); ORCA's "
                               "built-in xTB only has GFN2-xTB and GFN1-xTB"}
    else:
        result = run_orca(method)
    return {**result, "backend": backend, "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(), "runtime_s": time.monotonic() - clock}


def method_label(result: dict[str, Any]) -> str:
    """Level-of-theory label stored with a value, e.g. "xtb:GFN2-xTB", "dft:B97-3c",
    "dft:PBE0/def2-SVP" (dataset columns are keyed by it). xTB values get the same label
    whether tblite or ORCA ran them, since the numbers agree."""
    if result.get("backend") == "xtb":
        return f"xtb:{result.get('method')}"
    if result.get("method") in _ORCA_XTB_NAMES:
        return f"xtb:{_ORCA_XTB_NAMES[result['method']]}"
    basis = result.get("basis")
    return f"dft:{result.get('method')}" + (f"/{basis}" if basis else "")
