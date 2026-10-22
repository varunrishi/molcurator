"""What this installation can do, and the checks run before a run is started.

Everything here is read from the agent's own code where it can be, so the web app follows the
tools when they change:

- targets:      the single-number properties the tools compute (chem/properties.py:
                SCALAR_PROPERTIES), with their units (chem/orca.py: PROPERTIES)
- PREDICT:      GFN2-xTB through tblite where xTB can give the target, else B97-3c through
                ORCA (tools/predict.py: default_method); xTB falls back to ORCA's built-in xTB
                when tblite cannot be imported (chem/backends.py)
- generators:   GENERATE accepts only "stoned_selfies" (tools/generate.py)
- QM backends:  VALIDATE accepts only "orca" (tools/validate.py)
- LLM provider: only "anthropic" is built (agent/llm.py)
"""
import os
import platform
import shutil
from pathlib import Path

from molcurator.chem import orca, xtb
from molcurator.chem.backends import tblite_error
from molcurator.chem.properties import SCALAR_PROPERTIES
from molcurator.config import RunConfig
from molcurator.tools.predict import DFT_METHOD

from .settings import Settings

# Display names only; the list of targets itself comes from SCALAR_PROPERTIES.
_LABELS = {
    "energy": "Total energy", "homo_lumo_gap": "HOMO–LUMO gap", "dipole_moment": "Dipole moment",
    "polarizability": "Polarizability", "g_tensor": "EPR g-value", "s1_energy": "S1 energy",
    "t1_energy": "T1 energy", "s1_t1_gap": "S1–T1 gap (TADF)", "s0_t1_gap": "S0–T1 gap",
    "ionization_potential": "Ionization potential", "electron_affinity": "Electron affinity",
    "thermochemistry": "Gibbs free energy",
}


def _targets() -> list[dict]:
    out = []
    for name in SCALAR_PROPERTIES:
        by_xtb = name in xtb.PROPERTIES
        out.append({
            "name": name, "label": _LABELS.get(name, name), "units": orca.PROPERTIES[name].unit,
            "description": orca.PROPERTIES[name].description,
            "predict_method": "GFN2-xTB" if by_xtb else DFT_METHOD,  # tools/predict.py: default_method
            "needs_orca": not by_xtb, "supported": True, "reason": None,
        })
    return out


TARGETS = _targets()
GENERATORS = [
    {"name": "stoned_selfies", "label": "STONED SELFIES", "supported": True, "reason": None},
    {"name": "mol2mol", "label": "Mol2Mol (REINVENT4)", "supported": False, "reason": "Not built in GENERATE yet."},
]
QM_BACKENDS = [
    {"name": "orca", "label": "ORCA", "supported": True, "reason": None},
    {"name": "pyscf", "label": "PySCF", "supported": False, "reason": "Not built in VALIDATE yet."},
]
DECISION_MODES = [
    {"name": "rules", "label": "Rules (no LLM, instant)", "supported": True, "reason": None},
    {"name": "llm", "label": "LLM (Claude Haiku 4.5) with rule fallback", "supported": True,
     "reason": "Needs ANTHROPIC_API_KEY on the server."},
]


def supported(options: list[dict], name: str) -> bool:
    return any(o["name"] == name and o["supported"] for o in options)


def target_info(name: str) -> dict | None:
    return next((t for t in TARGETS if t["name"] == name), None)


def _executable(candidate: str | None) -> str | None:
    """candidate as an executable ORCA file; a folder is searched for orca or bin/orca (as OPI does)."""
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if path.is_dir():
        path = next((p for p in (path / "orca", path / "bin" / "orca") if p.is_file()), path)
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    return None


def find_orca(settings: Settings) -> tuple[str | None, str]:
    """(path, where it was found). Same order as the agent (chem/orca.py and OPI): ORCA_BIN,
    else OPI_ORCA, else ORCA_PATH in OPI's config file, else orca on PATH."""
    for source, candidate in (("ORCA_BIN", settings.env_value("ORCA_BIN")),
                              ("OPI_ORCA", settings.env_value("OPI_ORCA"))):
        if candidate:  # a set but wrong value is not skipped: the agent would use it and fail
            return _executable(candidate), source
    try:
        from opi.utils.config import get_config
        configured = (get_config() or {}).get("ORCA_PATH")
    except Exception:  # noqa: BLE001 - no OPI, or an unreadable config file
        configured = None
    if configured:
        return _executable(configured), "OPI config"
    return _executable(shutil.which("orca")), "PATH"


def tool_status(settings: Settings) -> dict:
    """Readiness of the property programs and keys. "found" for ORCA means an executable file;
    it does not prove ORCA runs (licence, Open MPI). xTB is "found" when tblite imports, or when
    ORCA is there to run its built-in xTB instead."""
    orca_path, orca_source = find_orca(settings)
    tblite_problem = tblite_error()
    if tblite_problem is None:
        xtb_via, xtb_note = "tblite", "GFN2-xTB runs in-process through tblite."
    elif orca_path:
        xtb_via, xtb_note = "orca", f"tblite cannot be imported ({tblite_problem}); xTB runs through ORCA's built-in xTB."
    else:
        xtb_via, xtb_note = None, f"tblite cannot be imported ({tblite_problem}) and ORCA was not found."
    return {
        "xtb": {"found": xtb_via is not None, "via": xtb_via, "note": xtb_note},
        "orca": {"found": orca_path is not None, "path": orca_path, "source": orca_source},
        "anthropic_key": {"set": bool(settings.env_value("ANTHROPIC_API_KEY"))},  # never the value itself
        "python": platform.python_version(),
    }


def capabilities() -> dict:
    return {"targets": TARGETS, "generators": GENERATORS, "qm_backends": QM_BACKENDS,
            "decision_modes": DECISION_MODES, "qm_approval": False}


def predict_level(config: RunConfig) -> dict:
    """What PREDICT computes for this config, for display: method, whether it needs ORCA, and
    whether its xTB values are corrected to DFT-like values."""
    method = config.predict.method or ("GFN2-xTB" if config.target.name in xtb.PROPERTIES else DFT_METHOD)
    by_xtb = xtb.is_xtb(method)
    label = method if by_xtb or not config.predict.basis else f"{method}/{config.predict.basis}"
    correction = config.predict.correction
    if correction is not None:
        label += " corrected to DFT-like"
    return {"method": method, "basis": config.predict.basis, "label": label, "xtb": by_xtb,
            "corrected": correction is not None,
            "correction_fitted_on": correction.fitted_on if correction else None}


def preflight(config: RunConfig, settings: Settings) -> tuple[list[str], list[str]]:
    """Problems (block the run) and warnings (shown, but the run may start) for a valid config.
    RunConfig itself already refuses unknown targets, wrong units and impossible PREDICT levels."""
    problems, warnings = [], []
    tools = tool_status(settings)
    level = predict_level(config)

    unsupported_generators = [g for g in config.generation.generators if not supported(GENERATORS, g)]
    if unsupported_generators or not supported(GENERATORS, config.generation.defaults.generator):
        problems.append("Only the stoned_selfies generator is built.")
    if level["xtb"]:
        if not tools["xtb"]["found"]:
            problems.append("PREDICT needs xTB, but tblite cannot be imported and ORCA was not found "
                            "(install the project's environment, or set ORCA_BIN).")
    elif not tools["orca"]["found"]:
        problems.append(f"PREDICT runs {level['label']} for {config.target.name}, which needs ORCA, "
                        "and ORCA was not found on the server (set ORCA_BIN).")
    if config.qm.enabled:
        if not supported(QM_BACKENDS, config.qm.backend):
            problems.append(f"QM backend '{config.qm.backend}' is not built yet; use orca.")
        elif not tools["orca"]["found"]:
            problems.append("Validate hits with QM is on, but ORCA was not found on the server "
                            "(set ORCA_BIN, or turn QM off).")
    if config.decisions == "llm":
        if not tools["anthropic_key"]["set"]:
            problems.append("LLM decisions need ANTHROPIC_API_KEY on the server; choose rules instead.")
        if (config.llm.provider or "anthropic") != "anthropic":
            problems.append("Only the anthropic LLM provider is built.")

    if not config.qm.enabled:
        warnings.append(f"QM is off: curated molecules will be {level['label']} or ML estimates, "
                        "not QM-confirmed hits.")
    if level["xtb"] and config.target.name == "homo_lumo_gap" and not level["corrected"]:
        warnings.append("PREDICT compares raw GFN2-xTB gaps with this window. xTB gaps sit well below DFT "
                        "gaps, so set predict.correction (as configs/homo_lumo.yaml does) for a DFT-level window.")
    if level["corrected"]:
        c = config.predict.correction
        warnings.append(f"PREDICT gaps are GFN2-xTB corrected to DFT-like values (typical error "
                        f"{c.residual_sd:g} eV; fitted on {c.fitted_on}, for xTB gaps {c.xtb_range[0]:g}–"
                        f"{c.xtb_range[1]:g} eV).")
    if not level["xtb"]:
        warnings.append(f"PREDICT runs {level['label']} through ORCA: minutes per molecule rather than seconds.")
    predicted_per_round = min(config.predict.n_xtb, config.generation.defaults.n_candidates)
    if config.train.min_examples > predicted_per_round * config.budget.max_rounds:
        warnings.append("With these settings the run likely never reaches train.min_examples PREDICT values, "
                        "so the ML model may never train.")
    return problems, warnings
