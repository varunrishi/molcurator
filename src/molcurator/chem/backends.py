# One entry point over the two property tools: xTB methods run in-process through tblite
# (chem/xtb.py), everything else through ORCA (chem/orca.py). PREDICT and VALIDATE call
# this, so both record what ran the same way.
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from molcurator.chem import orca, xtb
from molcurator.chem.settings import ChemistrySettings


def backend_for(method: str) -> str:
    return "xtb" if xtb.is_xtb(method) else "orca"


def calculate_property(elements: list[str], coordinates: list[list[float]], property_name: str, method: str,
                       basis: str | None, charge: int, multiplicity: int, workdir: Path,
                       settings: ChemistrySettings, extra_keywords: list[str] | None = None) -> dict[str, Any]:
    """Result dict of the matching tool, plus backend, timing and timestamps.

    Never upgrades the method: a property the method cannot give fails, so a pipeline step
    never runs a far more expensive calculation than its config asked for.
    """
    backend = backend_for(method)
    started, clock = datetime.now(UTC).isoformat(), time.monotonic()
    if backend == "xtb":
        result = xtb.calculate_property(elements, coordinates, property_name, method=method,
                                        charge=charge, multiplicity=multiplicity)
    else:
        result = orca.calculate_property(elements, coordinates, property_name, method=method, basis=basis,
                                         charge=charge, multiplicity=multiplicity, extra_keywords=extra_keywords,
                                         workdir=workdir, nprocs=settings.orca_nprocs,
                                         maxcore_mb=settings.orca_maxcore_mb, timeout_s=int(settings.timeout_s),
                                         allow_upgrade=False)
    return {**result, "backend": backend, "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(), "runtime_s": time.monotonic() - clock}


def method_label(result: dict[str, Any]) -> str:
    """Level-of-theory label stored with a value, e.g. "xtb:GFN2-xTB", "dft:B97-3c",
    "dft:PBE0/def2-SVP" (dataset columns are keyed by it)."""
    if result.get("backend") == "xtb":
        return f"xtb:{result.get('method')}"
    basis = result.get("basis")
    return f"dft:{result.get('method')}" + (f"/{basis}" if basis else "")
