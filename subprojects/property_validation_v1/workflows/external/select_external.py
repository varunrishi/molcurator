#!/usr/bin/env python3
"""Select previously unseen molecules from a QM9 SMILES source."""
import argparse, csv, random
from pathlib import Path
import pandas as pd
from rdkit import Chem

def canon(s):
    m = Chem.MolFromSmiles(str(s).strip())
    return Chem.MolToSmiles(m, canonical=True, isomericSmiles=True) if m else None

def read_smiles(path):
    for line in path.read_text(errors='replace').splitlines():
        x=line.strip()
        if not x or x.startswith('#'): continue
        parts=x.replace(',', ' ').split()
        # Accept one-SMILES-per-line, ID SMILES or SMILES ID.
        for token in parts[:3]:
            c=canon(token)
            if c is not None:
                yield token,c
                break

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path('/home/yo73juc/molcurator/QM9_smiles.txt'))
    p.add_argument('--existing',type=Path,default=Path('/work/AG_Presselt/MolCurator/ml276/ml_dataset.csv'))
    p.add_argument('--out',type=Path,default=Path('/work/AG_Presselt/MolCurator/external_test50'))
    p.add_argument('--n',type=int,default=50)
    p.add_argument('--seed',type=int,default=20261020)
    a=p.parse_args()
    base=pd.read_csv(a.existing)
    if 'canonical_smiles' in base: seen=set(base['canonical_smiles'].dropna().map(canon))
    else: seen=set(base['smiles'].dropna().map(canon))
    seen.discard(None)
    pool={}
    for smiles,c in read_smiles(a.source):
        if c not in seen and c not in pool:
            mol=Chem.MolFromSmiles(c)
            if Chem.GetFormalCharge(mol)==0 and not any(x.GetNumRadicalElectrons() for x in mol.GetAtoms()):
                pool[c]=smiles
    if len(pool)<a.n: raise SystemExit(f'Only {len(pool)} unseen neutral closed-shell structures found')
    rng=random.Random(a.seed)
    chosen=rng.sample(sorted(pool),a.n)
    rows=[{'molecule_id':f'test_{i:04d}', 'smiles':pool[c], 'canonical_smiles':c} for i,c in enumerate(chosen,1)]
    a.out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows).to_csv(a.out/'molecules.csv',index=False)
    print(f'Selected {len(rows)} new molecules from {len(pool)} unique eligible unseen structures')
    print('Saved:',a.out/'molecules.csv')
    print('First 5:\n',pd.DataFrame(rows).head().to_string(index=False))
if __name__=='__main__':main()
