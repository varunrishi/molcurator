"""What this installation can do, and the checks run before a run is started.

The limits below mirror the current tool code. When a tool gains a feature, update the
matching entry here so the web app stops disabling it:

- targets:      homo_lumo_gap (xTB PREDICT); s1_t1_gap needs ORCA, for TD-DFT PREDICT and VALIDATE
                (src/molcurator/tools/predict.py, src/molcurator/chem/backends.py)
- generators:   GENERATE accepts only "stoned_selfies" (src/molcurator/tools/generate.py)
- QM backends:  VALIDATE accepts only "orca" (.../tools/validate.py)
- LLM provider: only "anthropic" is built (src/molcurator/agent/llm.py)
"""
import os
import platform
import shutil
from pathlib import Path

from molcurator.config import RunConfig

from .settings import Settings

TARGETS = [
    {"name": "homo_lumo_gap", "label": "HOMO–LUMO gap", "units": "eV", "supported": True, "reason": None},
    {"name": "s1_t1_gap", "label": "S1–T1 gap (TADF)", "units": "eV", "supported": True,
     "reason": "Needs ORCA on the server: PREDICT runs B97-3c TD-DFT, since xTB cannot give S1 or T1."},
]
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

# Shown only for a HOMO-LUMO run without predict.correction, i.e. when the screen sees raw xTB gaps. From the
# repo's 60 xTB/B3LYP-def2-SVP pairs (data/properties/; scripts/fit_xtb_correction.py): B3LYP is ~2.2 eV higher.
XTB_OFFSET_NOTE = ("This run compares raw GFN2-xTB gaps with the window, without the xTB-to-DFT correction. "
                   "B3LYP/def2-SVP gaps are about 2.2 eV higher than xTB ones, so add predict.correction "
                   "(as in configs/homo_lumo.yaml) to read the window at the DFT level.")


def _tblite_version() -> str | None:
    """tblite's version if it can be imported here, else None."""
    try:
        from importlib.metadata import version
        import tblite  # noqa: F401
        return version("tblite")
    except Exception:  # noqa: BLE001 - not installed, or a broken build
        return None


def supported(options: list[dict], name: str) -> bool:
    return any(o["name"] == name and o["supported"] for o in options)


def find_executable(settings: Settings, env_name: str, program: str) -> str | None:
    """Same lookup order as the tools: the ORCA_BIN setting, else the program on PATH."""
    configured = settings.env_value(env_name)
    candidate = configured or shutil.which(program)
    if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return str(Path(candidate).resolve())
    return None


def tool_status(settings: Settings) -> dict:
    """Readiness of the external programs and keys. "found" means the file exists and is executable;
    it does not prove the program runs (licences, libraries)."""
    orca = find_executable(settings, "ORCA_BIN", "orca")
    # xTB runs in-process through tblite; without it, GFN2-xTB falls back to ORCA's built-in xTB (chem/backends.py)
    tblite = _tblite_version()
    xtb = f"tblite {tblite}" if tblite else f"ORCA's built-in xTB ({orca})" if orca else None
    return {
        "xtb": {"found": xtb is not None, "path": xtb},
        "orca": {"found": orca is not None, "path": orca},
        "anthropic_key": {"set": bool(settings.env_value("ANTHROPIC_API_KEY"))},  # never the value itself
        "python": platform.python_version(),
    }


def capabilities() -> dict:
    return {"targets": TARGETS, "generators": GENERATORS, "qm_backends": QM_BACKENDS,
            "decision_modes": DECISION_MODES, "qm_approval": False}


def preflight(config: RunConfig, settings: Settings) -> tuple[list[str], list[str]]:
    """Problems (block the run) and warnings (shown, but the run may start) for a valid config."""
    problems, warnings = [], []
    tools = tool_status(settings)

    if not supported(TARGETS, config.target.name):
        problems.append(f"Target '{config.target.name}' is not supported yet: PREDICT and VALIDATE "
                        "compute only homo_lumo_gap.")
    if config.target.units != "eV":
        problems.append("Target units must be eV.")
    unsupported_generators = [g for g in config.generation.generators if not supported(GENERATORS, g)]
    if unsupported_generators or not supported(GENERATORS, config.generation.defaults.generator):
        problems.append("Only the stoned_selfies generator is built.")
    if not tools["xtb"]["found"]:
        problems.append("xTB is not available on the server: install tblite (pip install tblite), "
                        "or set ORCA_BIN to use ORCA's built-in xTB.")
    if config.target.name == "s1_t1_gap" and not tools["orca"]["found"]:
        problems.append("The S1–T1 gap needs ORCA on the server (set ORCA_BIN): xTB cannot give S1 or T1.")
    if config.qm.enabled:
        if not supported(QM_BACKENDS, config.qm.backend):
            problems.append(f"QM backend '{config.qm.backend}' is not built yet; use orca.")
        elif not tools["orca"]["found"]:
            problems.append("QM is on but ORCA was not found on the server (set ORCA_BIN).")
    if config.decisions == "llm":
        if not tools["anthropic_key"]["set"]:
            problems.append("LLM decisions need ANTHROPIC_API_KEY on the server; choose rules instead.")
        if (config.llm.provider or "anthropic") != "anthropic":
            problems.append("Only the anthropic LLM provider is built.")

    if not config.qm.enabled:
        warnings.append("QM validation is switched off: curated molecules will be xTB or ML estimates, "
                        "not QM-confirmed hits.")
    if config.target.name == "homo_lumo_gap" and config.predict.correction is None:
        warnings.append(XTB_OFFSET_NOTE)
    xtb_per_round = min(config.predict.n_xtb, config.generation.defaults.n_candidates)
    if config.train.min_examples > xtb_per_round * config.budget.max_rounds:
        warnings.append("With these settings the run likely never reaches train.min_examples xTB values, "
                        "so the ML model may never train.")
    return problems, warnings
