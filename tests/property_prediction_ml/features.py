"""Structure features shared by local training and independent inference."""
import numpy as np
from rdkit import Chem,DataStructs
from rdkit.Chem import Descriptors,rdMolDescriptors,rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold

FP_SIZE=2048
DESCRIPTORS=['molecular_weight','tpsa','logp','h_donors','h_acceptors','rotatable_bonds','rings','fraction_csp3','heavy_atoms','nitrogen_atoms','oxygen_atoms','fluorine_atoms','aromatic_atoms']
FF_NAMES=['ff_energy_kcal_mol','sampled_ff_weight','n_unique_minima','n_converged_minima']
GENERATOR=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=FP_SIZE,includeChirality=True)

def describe(smiles):
    mol=Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol))!=1:raise ValueError('one valid connected molecule required')
    if Chem.GetFormalCharge(mol) or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):raise ValueError('neutral closed-shell molecules required')
    fp=GENERATOR.GetFingerprint(mol)
    bits=GENERATOR.GetFingerprintAsNumPy(mol).astype(float)
    values=np.asarray([Descriptors.MolWt(mol),rdMolDescriptors.CalcTPSA(mol),Descriptors.MolLogP(mol),rdMolDescriptors.CalcNumHBD(mol),rdMolDescriptors.CalcNumHBA(mol),rdMolDescriptors.CalcNumRotatableBonds(mol),rdMolDescriptors.CalcNumRings(mol),rdMolDescriptors.CalcFractionCSP3(mol),mol.GetNumHeavyAtoms(),sum(a.GetAtomicNum()==7 for a in mol.GetAtoms()),sum(a.GetAtomicNum()==8 for a in mol.GetAtoms()),sum(a.GetAtomicNum()==9 for a in mol.GetAtoms()),sum(a.GetIsAromatic() for a in mol.GetAtoms())],dtype=float)
    scaffold=MurckoScaffold.MurckoScaffoldSmiles(mol=mol,includeChirality=False) or 'ACYCLIC'
    return np.concatenate([bits,values]),scaffold,fp
