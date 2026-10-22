# 3D structure helpers: RDKit conformer embedding + force-field pre-optimisation,
# and reading / writing XYZ files.
#
# lowest_ff_conformer: SMILES -> ETKDG conformer ensemble -> MMFF94 minimisation -> the
# lowest converged minimum (the geometry PREDICT and VALIDATE compute properties at), with
# a report of how it was chosen. Unique minima (0.25 A heavy-atom RMSD) give a force-field
# Boltzmann weight for the chosen one; it is conditional on the sampled set.
import math
import re
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

from molcurator.chem.settings import ChemistrySettings, load_settings

KCAL_PER_MOL_K = 0.00198720425864083  # gas constant


class GeometryError(ValueError):
    """A molecule that cannot be given a geometry; stage and code say where and why."""

    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage, self.code = stage, code


def _embed(mol: Chem.Mol, settings: ChemistrySettings) -> tuple[list[int], str]:
    """Conformer ids, and how they were made: an ensemble, or one random-coordinate fallback."""
    params = AllChem.ETKDGv3()
    params.randomSeed, params.numThreads, params.pruneRmsThresh = settings.random_seed, 1, -1
    try:
        ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=settings.nconfs, params=params))
    except Exception as exc:
        raise GeometryError("embedding", "embedding_failed", str(exc)) from exc
    if ids:
        return ids, "conformer_ensemble"
    # Some ring systems fail ETKDG's ensemble; one random-coordinate embedding usually works.
    params.useRandomCoords = True
    cid = AllChem.EmbedMolecule(mol, params)
    if cid < 0:
        raise GeometryError("embedding", "no_conformers", "RDKit could not embed a 3D geometry")
    return [cid], "single_embedding_fallback"


def lowest_ff_conformer(smiles: str, settings: ChemistrySettings | None = None) -> tuple[str, dict]:
    """XYZ text of the lowest converged MMFF94 minimum, and a report of the selection.

    The report carries the formal charge and number of radical electrons, which set the
    charge and multiplicity of the electronic-structure calculations.
    """
    settings = settings or load_settings()
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol)) != 1:
        raise GeometryError("structure", "invalid_or_disconnected", "one valid connected molecule required")
    charge = Chem.GetFormalCharge(mol)
    radicals = sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())
    mol = Chem.AddHs(mol)
    ids, source = _embed(mol, settings)
    if not AllChem.MMFFHasAllMoleculeParams(mol):
        raise GeometryError("force_field", "mmff_parameters_unavailable", "MMFF94 has no parameters for this molecule")
    properties = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94")
    minima = []
    for cid in ids:
        field = AllChem.MMFFGetMoleculeForceField(mol, properties, confId=cid)
        status = field.Minimize(maxIts=settings.mmff_max_iterations, forceTol=settings.mmff_force_tolerance,
                                energyTol=settings.mmff_energy_tolerance)
        energy = field.CalcEnergy()
        if status == 0 and math.isfinite(energy):
            minima.append((energy, cid))
    if not minima:
        raise GeometryError("force_field", "no_converged_conformers", "no MMFF94 minimisation converged")
    minima.sort()
    heavy = Chem.RemoveHs(mol)
    unique: list[tuple[float, int]] = []
    for energy, cid in minima:
        # Copies are aligned, so the comparison cannot move the selected geometry.
        if all(rdMolAlign.GetBestRMS(Chem.Mol(heavy), Chem.Mol(heavy), prbId=cid, refId=other,
                                     maxMatches=10000) >= settings.rms_cutoff_angstrom for _, other in unique):
            unique.append((energy, cid))
    energy, cid = unique[0]
    weight = 1 / sum(math.exp(-(e - energy) / (KCAL_PER_MOL_K * settings.temperature_k)) for e, _ in unique)
    report = {"force_field": "MMFF94", "geometry_source": source, "formal_charge": charge,
              "radical_electrons": radicals, "n_embedded": len(ids), "n_converged": len(minima),
              "n_unique": len(unique), "selected_conformer_id": cid, "selected_ff_energy_kcal_mol": energy,
              "selected_ff_boltzmann_weight": weight, "unique_ff_energies_kcal_mol": [e for e, _ in unique],
              "temperature_k": settings.temperature_k, "rms_cutoff_angstrom": settings.rms_cutoff_angstrom,
              "random_seed": settings.random_seed, "n_requested": settings.nconfs}
    return Chem.MolToXYZBlock(mol, confId=cid), report


def read_xyz(path: str | Path) -> tuple[list[str], list[list[float]]]:
    """Element symbols and coordinates (angstrom) of an XYZ file, rejecting malformed or
    non-finite geometries before they reach a calculation."""
    lines = Path(path).read_text().splitlines()
    try:
        n = int(lines[0])
    except (IndexError, ValueError) as exc:
        raise ValueError("XYZ file has no atom count") from exc
    rows = [line.split() for line in lines[2:] if line.strip()]
    if n < 1 or len(rows) != n:
        raise ValueError(f"XYZ file says {n} atoms but has {len(rows)}")
    table = Chem.GetPeriodicTable()
    elements, coordinates = [], []
    for fields in rows:
        try:
            if len(fields) != 4 or table.GetAtomicNumber(fields[0]) < 1:
                raise ValueError
            xyz = [float(v) for v in fields[1:]]
        except (ValueError, RuntimeError) as exc:  # RDKit raises RuntimeError for unknown symbols
            raise ValueError(f"invalid XYZ atom line: {' '.join(fields)}") from exc
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError("non-finite XYZ coordinate")
        elements.append(fields[0])
        coordinates.append(xyz)
    return elements, coordinates


def multiplicity_from_report(report: dict) -> int:
    """Spin multiplicity 2S+1 for the radical electrons in the SMILES (high spin)."""
    return report["radical_electrons"] + 1


def with_comment(xyz: str, comment: str) -> str:
    """The XYZ text with its comment (second) line replaced."""
    lines = xyz.splitlines()
    return "\n".join([lines[0], comment, *lines[2:]]) + "\n"


def charge_multiplicity_comment(charge: int, multiplicity: int) -> str:
    """XYZ comment line that carries the electronic state from PREDICT to VALIDATE."""
    return f"charge={charge} multiplicity={multiplicity}"


def read_charge_multiplicity(path: str | Path) -> tuple[int, int]:
    """Charge and multiplicity from an XYZ comment line written by PREDICT; 0 and 1 if absent."""
    comment = Path(path).read_text().splitlines()[1] if Path(path).is_file() else ""
    charge = re.search(r"\bcharge=(-?\d+)", comment)
    multiplicity = re.search(r"\bmultiplicity=(\d+)", comment)
    return int(charge.group(1)) if charge else 0, int(multiplicity.group(1)) if multiplicity else 1
