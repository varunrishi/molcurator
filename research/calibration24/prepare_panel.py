#!/usr/bin/env python3
"""Create a fixed, predeclared train/test panel; no QC jobs launched."""
import argparse,csv
from pathlib import Path
from rdkit import Chem
# Small neutral closed-shell organic diversity panel; scaffold groups kept intact.
GROUPS={
 'benzene':['c1ccccc1','Cc1ccccc1','COc1ccccc1','Nc1ccccc1'],
 'pyridine':['c1ccncc1','Cc1ccncc1','COc1ccncc1','Nc1ccncc1'],
 'five_ring':['c1ccoc1','c1ccsc1','c1cc[nH]c1','c1cnoc1'],
 'carbonyl':['CC(=O)C','CC(=O)OC','CC(=O)N','O=Cc1ccccc1'],
 'nitrile':['CC#N','CCC#N','N#Cc1ccccc1','COCC#N'],
 'alkene':['C=CC','C=CC=C','C=CCO','C=CC#N'],
}
# Train/test split predetermined before electronic properties are observed.
TEST_GROUPS={'five_ring','nitrile'}
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
a.out.parent.mkdir(parents=True,exist_ok=True)
if a.out.exists(): raise SystemExit(f'Refusing to overwrite existing manifest: {a.out}')
rows=[]; seen=set()
for group,smiles_list in GROUPS.items():
 for s in smiles_list:
  mol=Chem.MolFromSmiles(s)
  if mol is None or Chem.GetFormalCharge(mol) or any(x.GetNumRadicalElectrons() for x in mol.GetAtoms()): raise SystemExit(f'Invalid panel molecule: {s}')
  canonical=Chem.MolToSmiles(mol)
  if canonical in seen: raise SystemExit(f'Duplicate: {s}')
  seen.add(canonical)
  rows.append(dict(candidate_id=f'cal_{len(rows)+1:03d}',smiles=canonical,group=group,split='test' if group in TEST_GROUPS else 'train'))
with a.out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['candidate_id','smiles','group','split']);w.writeheader();w.writerows(rows)
print(f'Wrote {len(rows)} molecules: {sum(r["split"]=="train" for r in rows)} train, {sum(r["split"]=="test" for r in rows)} test to {a.out}')
