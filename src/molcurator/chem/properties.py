"""Extract explicit orbital/dipole values; never infer absolute orbitals from a gap."""
import re

from .calculations import NUMBER, number, orca_gap, xtb_gap

UNITS = {"homo_lumo_gap": "eV", "homo": "eV", "lumo": "eV", "dipole": "D"}


def extract_properties(text: str, backend: str) -> dict[str, float]:
    """Require the existing convergence checks before accepting property values."""
    if backend == "xtb":
        values = {"homo_lumo_gap": xtb_gap(text)}
        for orbital in ("homo", "lumo"):
            lines = re.findall(r"^.*\(" + orbital + r"\).*$", text, re.I | re.M)
            if lines:
                # xTB's marked orbital rows end in E/eV, before (HOMO)/(LUMO).
                prefix = re.split(r"\(" + orbital + r"\)", lines[-1], flags=re.I)[0]
                tokens = prefix.split()
                if tokens and tokens[0].isdigit() and len(tokens) >= 3:
                    values[orbital] = number(tokens[-1])
        sections = re.split(r"^\s*molecular dipole:\s*$", text, flags=re.I | re.M)
        if len(sections) > 1:
            match = re.search(r"^\s*full:\s+(" + NUMBER + r")\s+(" + NUMBER
                              + r")\s+(" + NUMBER + r")\s+(" + NUMBER + r")\s*$",
                              sections[-1], re.M)
            if match:
                values["dipole"] = number(match.group(4))
    elif backend == "orca":
        values = {"homo_lumo_gap": orca_gap(text)}
        section = re.split(r"^\s*ORBITAL ENERGIES\s*$", text, flags=re.M)[-1]
        occupied, virtual = [], []
        for line in section.splitlines():
            match = re.fullmatch(r"\s*\d+\s+(" + NUMBER + r")\s+(" + NUMBER
                                 + r")\s+(" + NUMBER + r")\s*", line)
            if match:
                occupancy, _, energy = map(number, match.groups())
                (occupied if occupancy else virtual).append(energy)
            elif occupied and virtual:
                break
        values.update(homo=max(occupied), lumo=min(virtual))
        sections = re.split(r"^\s*DIPOLE MOMENT\s*$", text, flags=re.M)
        if len(sections) > 1:
            match = re.search(r"^\s*Magnitude\s*\(Debye\)\s*:\s*(" + NUMBER + r")",
                              sections[-1], re.I | re.M)
            if match:
                values["dipole"] = number(match.group(1))
    else:
        raise ValueError("property parser requires xtb or orca")
    if "dipole" in values and values["dipole"] < 0:
        raise ValueError("negative dipole magnitude")
    return values
