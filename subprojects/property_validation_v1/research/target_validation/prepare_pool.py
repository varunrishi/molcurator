#!/usr/bin/env python3
"""Sample unused QM9 molecules for prospective xTB-only screening."""
import argparse,csv,random
from pathlib import Path
from rdkit import Chem, RDLogger
RDLogger.DisableLog('rdApp.error')

def canon(s):
    m=Chem.MolFromSmiles(str(s).strip())
    if m is None or Chem.GetFormalCharge(m) or any(a.GetNumRadicalElectrons() for a in m.GetAtoms()) or len(Chem.GetMolFrags(m))!=1: return None
    return Chem.MolToSmiles(m,isomericSmiles=True)

def read(path):
    if not path.exists():return
    with path.open(errors='replace') as f:
        first=f.readline();f.seek(0)
        if ',' in first and 'smiles' in first.lower():
            for r in csv.DictReader(f):
                if r.get('smiles'):yield r['smiles']
        else:
            for ln in f:
                if ln.strip() and not ln.startswith('#'):yield ln.split()[0]

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path('/home/yo73juc/molcurator/QM9_smiles.txt'));p.add_argument('--root',type=Path,default=Path('/work/AG_Presselt/MolCurator'));p.add_argument('--output',type=Path,required=True);p.add_argument('--n',type=int,default=600);p.add_argument('--seed',type=int,default=20261021);a=p.parse_args()
    if a.output.exists():raise SystemExit('Refusing to overwrite an existing pool manifest')
    known=set()
    for rel in ['qm9_100/molecules.csv','qm9_200/molecules.csv','qm9_400/molecules.csv','qm9_500/molecules.csv','ml276/ml_dataset.csv','external_test50/molecules.csv','calibration24/panel.csv','design_qm9_0023/molecules.csv','design_iteration2/molecules.csv']:
        for smi in read(a.root/rel):
            c=canon(smi)
            if c:known.add(c)
    pool={}
    for smi in read(a.source):
        c=canon(smi)
        if c and c not in known:pool[c]=c
    values=list(pool);random.Random(a.seed).shuffle(values)
    if len(values)<a.n:raise SystemExit(f'Insufficient valid unseen molecules: {len(values)} < {a.n}')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['candidate_id','smiles']);w.writerows((f'pool_{i:04d}',s) for i,s in enumerate(values[:a.n]))
    print(f'Wrote {a.n} candidates; excluded {len(known)} known structures')
if __name__=='__main__':main()
