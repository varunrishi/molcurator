"""Neutral closed-shell geometries and FF weights, adapted from property_validation_v1."""
import math
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign
from .prevalidation import PreparationError


def lowest_ff_conformer(smiles: str, nconfs: int | None = None, temperature: float | None = None):
    """Select lowest converged FF minimum; weight unique sampled minima at 0.25 Å RMSD."""
    from .settings import load_settings
    settings = load_settings()
    nconfs = settings.nconfs if nconfs is None else nconfs
    temperature = settings.temperature_k if temperature is None else temperature
    if nconfs < 1 or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("positive conformer count and temperature required")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol)) != 1:
        raise PreparationError("structure", "invalid_or_disconnected_structure", "one valid connected molecule required")
    charge = Chem.GetFormalCharge(mol)
    radicals = sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())
    if charge:
        raise PreparationError("structure", "unsupported_charge", "iteration 1 supports neutral molecules only",
                               formal_charge=charge, radical_electrons=radicals)
    if radicals:
        raise PreparationError("structure", "unsupported_radical", "iteration 1 supports closed-shell molecules only",
                               formal_charge=charge, radical_electrons=radicals)
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = settings.random_seed
    params.numThreads = 1
    params.pruneRmsThresh = -1
    try:
        ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=nconfs, params=params))
    except Exception as exc:
        raise PreparationError("embedding", "embedding_failed", str(exc)) from exc
    if not ids:
        raise PreparationError("embedding", "no_conformers", "no embedded conformers")
    if not AllChem.MMFFHasAllMoleculeParams(mol):
        raise PreparationError("force_field", "mmff_parameters_unavailable", "MMFF94 parameters unavailable; no alternative force field is used")
    method = "MMFF94"
    properties = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94")
    results = []
    for cid in ids:
        field = AllChem.MMFFGetMoleculeForceField(mol, properties, confId=cid)
        status = field.Minimize(maxIts=settings.mmff_max_iterations,
                                forceTol=settings.mmff_force_tolerance,
                                energyTol=settings.mmff_energy_tolerance)
        results.append((status, field.CalcEnergy()))
    minima = sorted((float(e), cid) for cid, (status, e) in zip(ids, results)
                    if status == 0 and math.isfinite(e))
    if not minima:
        raise PreparationError("force_field", "no_converged_conformers", "no converged force-field conformers")
    heavy = Chem.RemoveHs(mol)
    unique = []
    for energy, cid in minima:
        # Align copies so clustering cannot move the selected geometry.
        if all(rdMolAlign.GetBestRMS(Chem.Mol(heavy), Chem.Mol(heavy),
                                    prbId=cid, refId=other, maxMatches=10000) >= settings.rms_cutoff_angstrom
               for _, other in unique):
            unique.append((energy, cid))
    energy, cid = unique[0]
    weight = 1 / sum(math.exp(-(e - energy) / (0.00198720425864083 * temperature))
                     for e, _ in unique)
    report = dict(policy="lowest_converged_mmff94_energy", electronic_geometry_policy="single_point_on_selected_mmff94_geometry", force_field=method,
                  formal_charge=charge, radical_electrons=radicals,
                  temperature_k=temperature, n_embedded=len(ids), n_converged=len(minima),
                  n_unique=len(unique), selected_conformer_id=cid,
                  selected_ff_energy_kcal_mol=energy, selected_ff_boltzmann_weight=weight,
                  unique_ff_energies_kcal_mol=[e for e, _ in unique],
                  weight_scope="unique sampled converged FF minima; no energy-window truncation",
                  rms_cutoff_angstrom=settings.rms_cutoff_angstrom, random_seed=settings.random_seed,
                  n_requested=nconfs, mmff_max_iterations=settings.mmff_max_iterations,
                  mmff_force_tolerance=settings.mmff_force_tolerance,
                  mmff_energy_tolerance=settings.mmff_energy_tolerance)
    try:
        xyz = Chem.MolToXYZBlock(mol, confId=cid)
    except Exception as exc:
        raise PreparationError("xyz_export", "xyz_creation_failed", str(exc)) from exc
    return xyz, report


def xyz_symbols(path: Path) -> list[str]:
    """Reject malformed/nonfinite geometries before passing them between programs."""
    lines = path.read_text().splitlines()
    n = int(lines[0])
    if n < 1 or len(lines) != n + 2:
        raise ValueError("invalid XYZ atom count")
    symbols = []
    table = Chem.GetPeriodicTable()
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or table.GetAtomicNumber(fields[0]) < 1:
            raise ValueError("invalid XYZ atom")
        if not all(math.isfinite(float(v)) for v in fields[1:]):
            raise ValueError("nonfinite XYZ coordinate")
        symbols.append(fields[0])
    return symbols
