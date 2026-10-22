"""What this installation can do, and the checks run before a run is started.

The limits below mirror the current tool code. When a tool gains a feature, update the
matching entry here so the web app stops disabling it:

- targets:      PREDICT/VALIDATE accept only "homo_lumo_gap" in eV
                (subprojects/property_validation_v1/.../chem/calculations.py)
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
    {"name": "s1_t1_gap", "label": "S1–T1 gap (TADF)", "units": "eV", "supported": False,
     "reason": "PREDICT and VALIDATE compute only HOMO–LUMO gaps in this version."},
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

# From the repo's own analysis (subprojects/property_validation_v1/reports/local_xtb_validation_20261021/
# analysis_report.md): B3LYP/def2-SVP minus local GFN2-xTB gap, mean over 60 molecules.
XTB_OFFSET_NOTE = ("The screen compares raw GFN2-xTB gaps with this window. In the repo's local analysis, "
                   "B3LYP/def2-SVP gaps were on average 2.55 eV higher than xTB gaps (60 molecules), so xTB "
                   "values in the window may not be in it at the DFT level.")


def supported(options: list[dict], name: str) -> bool:
    return any(o["name"] == name and o["supported"] for o in options)


def find_executable(settings: Settings, env_name: str, program: str) -> str | None:
    """Same lookup order as the tools: the XTB_BIN/ORCA_BIN setting, else the program on PATH."""
    configured = settings.env_value(env_name)
    candidate = configured or shutil.which(program)
    if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return str(Path(candidate).resolve())
    return None


def tool_status(settings: Settings) -> dict:
    """Readiness of the external programs and keys. "found" means the file exists and is executable;
    it does not prove the program runs (licences, libraries)."""
    xtb = find_executable(settings, "XTB_BIN", "xtb")
    orca = find_executable(settings, "ORCA_BIN", "orca")
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
        problems.append("xTB was not found on the server (set XTB_BIN or put xtb on PATH).")
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
        warnings.append("QM is off: curated molecules will be xTB or ML estimates, not QM-confirmed hits.")
    if config.target.name == "homo_lumo_gap":
        warnings.append(XTB_OFFSET_NOTE)
    xtb_per_round = min(config.predict.n_xtb, config.generation.defaults.n_candidates)
    if config.train.min_examples > xtb_per_round * config.budget.max_rounds:
        warnings.append("With these settings the run likely never reaches train.min_examples xTB values, "
                        "so the ML model may never train.")
    return problems, warnings
