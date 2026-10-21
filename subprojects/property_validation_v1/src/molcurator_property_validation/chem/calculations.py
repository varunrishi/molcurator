"""xTB/ORCA execution and gap readers; patterns adapted from property_validation_v1."""
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def number(value: str) -> float:
    result = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise ValueError("nonfinite property")
    return result


def safe_id(candidate_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", candidate_id):
        raise ValueError("candidate id must contain only letters, digits, underscores or hyphens")
    return candidate_id


def run(binary_env: str, fallback: str, args: list[str], folder: Path, log: Path):
    """One process attempt, no hidden retries; stdout and stderr retained together."""
    executable = os.environ.get(binary_env) or fallback
    resolved = shutil.which(executable)
    if resolved is None:
        raise FileNotFoundError(f"{binary_env}: executable not found: {executable}")
    timeout = float(os.environ.get("MOLCURATOR_QC_TIMEOUT_S", "600"))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("MOLCURATOR_QC_TIMEOUT_S must be positive and finite")
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with log.open("w") as output:
        result = subprocess.run([str(Path(resolved).resolve()), *args], cwd=folder,
                                stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout, env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"{fallback} exited with code {result.returncode}; see {log}")


def xtb_gap(text: str) -> float:
    if not re.search(r"normal termination of xtb", text, re.I):
        raise ValueError("xTB did not terminate normally")
    if not re.search(r"GEOMETRY OPTIMIZATION CONVERGED", text, re.I):
        raise ValueError("xTB geometry optimization did not converge")
    matches = re.findall(r"HOMO-LUMO\s+GAP\s+" + f"({NUMBER})" + r"\s+eV", text, re.I)
    if not matches:
        raise ValueError("missing xTB HOMO-LUMO gap")
    gap = number(matches[-1])
    if gap < 0:
        raise ValueError("negative xTB gap")
    return gap


def orca_gap(text: str) -> float:
    if "ORCA TERMINATED NORMALLY" not in text or "SCF CONVERGED AFTER" not in text:
        raise ValueError("ORCA termination or SCF convergence not confirmed")
    sections = re.split(r"^\s*ORBITAL ENERGIES\s*$", text, flags=re.M)
    if len(sections) < 2:
        raise ValueError("missing ORCA orbital energies")
    occupied, virtual = [], []
    for line in sections[-1].splitlines():
        match = re.fullmatch(r"\s*\d+\s+(" + NUMBER + r")\s+(" + NUMBER
                             + r")\s+(" + NUMBER + r")\s*", line)
        if match:
            occupancy, _, energy = map(number, match.groups())
            if occupancy not in (0.0, 2.0):
                raise ValueError("only closed-shell orbital tables supported")
            (occupied if occupancy else virtual).append(energy)
        elif occupied and virtual:
            break
    if not occupied or not virtual:
        raise ValueError("incomplete final ORCA orbital table")
    gap = min(virtual) - max(occupied)
    if gap < 0:
        raise ValueError("negative ORCA gap")
    return gap


def require_gap_target(target):
    if target.name != "homo_lumo_gap" or target.units != "eV":
        raise ValueError("iteration 1 supports homo_lumo_gap in eV only")
