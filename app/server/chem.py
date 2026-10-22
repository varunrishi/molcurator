"""Quick checks of a seed molecule before a run, with RDKit (the library the agent uses).

The agent canonicalises seeds with RDKit, so this canonical SMILES is what the run will record.
The 3D structure is a single quick conformer for preview only: PREDICT prepares its own
geometry (30 conformers, MMFF94) before any property is computed.
"""
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors


def inspect_smiles(smiles: str, with_xyz: bool = True) -> dict:
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None or mol.GetNumAtoms() == 0:
        return {"valid": False, "canonical": None, "problems": ["Not a valid SMILES."], "xyz": None}

    # Shown as notes, not blocks. PREDICT computes charged and open-shell molecules (it reads charge and
    # multiplicity), but the ML model learns only neutral closed-shell ones and GENERATE rejects radicals.
    problems = []
    if Chem.GetFormalCharge(mol) != 0:
        problems.append("Charged molecule: xTB handles it, but the ML model learns only from neutral "
                        "molecules, so charged candidates get no ML estimate.")
    if Descriptors.NumRadicalElectrons(mol) > 0:
        problems.append("Radical: xTB handles it, but GENERATE rejects radical candidates and the ML model "
                        "learns only from closed-shell molecules.")
    if len(Chem.GetMolFrags(mol)) > 1:
        problems.append("More than one fragment: PREDICT needs one connected molecule, so its children "
                        "will likely fail in xTB.")

    return {
        "valid": True,
        "canonical": Chem.MolToSmiles(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "formula": Chem.rdMolDescriptors.CalcMolFormula(mol),
        "problems": problems,
        "xyz": preview_xyz(mol) if with_xyz else None,
    }


def preview_xyz(mol: Chem.Mol) -> str | None:
    """One ETKDG conformer tidied with MMFF94, as XYZ text; None if embedding fails."""
    mol = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol, randomSeed=42) != 0:
        return None
    if AllChem.MMFFHasAllMoleculeParams(mol):
        AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
    return Chem.MolToXYZBlock(mol)
