"""Neutral closed-shell geometries and FF weights, adapted from property_validation_v1."""
import math
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign


def lowest_ff_conformer(smiles: str, nconfs: int = 30, temperature: float = 298.15):
    """Select lowest converged FF minimum; weight unique sampled minima at 0.25 Å RMSD."""
    if nconfs < 1 or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("positive conformer count and temperature required")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError("one valid connected molecule required")
    if Chem.GetFormalCharge(mol) or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise ValueError("iteration 1 supports neutral closed-shell molecules only")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    params.numThreads = 1
    params.pruneRmsThresh = -1
    ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=nconfs, params=params))
    if not ids:
        raise ValueError("no embedded conformers")
    if AllChem.MMFFHasAllMoleculeParams(mol):
        method = "MMFF94"
        results = AllChem.MMFFOptimizeMoleculeConfs(mol, numThreads=1, maxIters=500)
    else:
        method = "UFF"
        results = AllChem.UFFOptimizeMoleculeConfs(mol, numThreads=1, maxIters=500)
    minima = sorted((float(e), cid) for cid, (status, e) in zip(ids, results)
                    if status == 0 and math.isfinite(e))
    if not minima:
        raise ValueError("no converged force-field conformers")
    heavy = Chem.RemoveHs(mol)
    unique = []
    for energy, cid in minima:
        # Align copies so clustering cannot move the selected geometry.
        if all(rdMolAlign.GetBestRMS(Chem.Mol(heavy), Chem.Mol(heavy),
                                    prbId=cid, refId=other, maxMatches=10000) >= 0.25
               for _, other in unique):
            unique.append((energy, cid))
    energy, cid = unique[0]
    weight = 1 / sum(math.exp(-(e - energy) / (0.00198720425864083 * temperature))
                     for e, _ in unique)
    report = dict(policy="lowest_converged_ff_energy", force_field=method,
                  temperature_k=temperature, n_embedded=len(ids), n_converged=len(minima),
                  n_unique=len(unique), selected_conformer_id=cid,
                  selected_ff_energy_kcal_mol=energy, selected_ff_boltzmann_weight=weight,
                  unique_ff_energies_kcal_mol=[e for e, _ in unique],
                  weight_scope="unique sampled converged FF minima; no energy-window truncation",
                  rms_cutoff_angstrom=0.25, random_seed=42)
    return Chem.MolToXYZBlock(mol, confId=cid), report


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
