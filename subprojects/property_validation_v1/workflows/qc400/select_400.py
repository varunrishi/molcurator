#!/usr/bin/env python3
"""Select 400 unused neutral closed-shell QM9 SMILES, exclude all known sets."""
import argparse,csv,random
from pathlib import Path
from rdkit import Chem

def canon(s):
    m=Chem.MolFromSmiles(str(s).strip())
    if m is None or Chem.GetFormalCharge(m)!=0 or any(a.GetNumRadicalElectrons() for a in m.GetAtoms()): return None
    return Chem.MolToSmiles(m,isomericSmiles=True)

def read_smiles(path):
    path=Path(path)
    if not path.exists(): return
    with path.open(errors='replace') as f:
        first=f.readline(); f.seek(0)
        if 'smiles' in first.lower() and ',' in first:
            for row in csv.DictReader(f):
                if row.get('smiles'): yield row['smiles']
        else:
            for line in f:
                s=line.strip()
                if not s or s.startswith('#'):continue
                # Standard plain QM9 list: one SMILES per line
                yield s.split()[0]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',default='/home/yo73juc/molcurator/QM9_smiles.txt')
    ap.add_argument('--root',default='/work/AG_Presselt/MolCurator')
    ap.add_argument('--count',type=int,default=400);ap.add_argument('--seed',type=int,default=20261020)
    a=ap.parse_args(); root=Path(a.root); out=root/'qm9_400';out.mkdir(parents=True,exist_ok=True)
    known=set()
    paths=[root/'qm9_100/molecules.csv',root/'qm9_200/molecules.csv',root/'ml276/ml_dataset.csv',
           root/'external_test50/molecules.csv',root/'design_qm9_0023/molecules.csv',root/'design_iteration2/molecules.csv',out/'molecules.csv']
    for p in paths:
        if p.exists():
            for s in read_smiles(p):
                c=canon(s)
                if c:known.add(c)
    unique={}
    for s in read_smiles(a.source):
        c=canon(s)
        if c and c not in known:unique[c]=c
    pool=list(unique);random.Random(a.seed).shuffle(pool)
    if len(pool)<a.count:raise SystemExit(f'Only {len(pool)} unseen valid molecules; need {a.count}. Check source format.')
    selected=pool[:a.count]
    p=out/'molecules.csv'
    if p.exists():raise SystemExit('Output exists; refusing to overwrite existing batch')
    with p.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['molecule_id','smiles'])
        for i,s in enumerate(selected,1):w.writerow([f'qm9_new_{i:04d}',s])
    print(f'Wrote {len(selected)} unique molecules to {p}; excluded {len(known)} known structures; seed={a.seed}')
if __name__=='__main__':main()
