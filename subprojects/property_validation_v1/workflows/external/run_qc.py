#!/usr/bin/env python3
"""Run one QM9 molecule through MMFF94 -> GFN2-xTB -> ORCA TDA-PBE0/def2-SVP."""
import argparse, os, subprocess, sys
from pathlib import Path
import pandas as pd
from rdkit import Chem
from rdkit.Chem import AllChem

def xyz(m,path):
    conf=m.GetConformer()
    with path.open('w') as f:
        f.write(f'{m.GetNumAtoms()}\nRDKit ETKDG/MMFF94\n')
        for a in m.GetAtoms():
            v=conf.GetAtomPosition(a.GetIdx())
            f.write(f'{a.GetSymbol()} {v.x:.10f} {v.y:.10f} {v.z:.10f}\n')

def execute(command,cwd,log):
    with log.open('w') as f:
        result=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=False)
    if result.returncode:
        raise RuntimeError(f'Command failed (exit {result.returncode}): {command}; see {log}')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('/work/AG_Presselt/MolCurator/external_test50'))
    p.add_argument('--index',type=int,required=True,help='zero-based CSV row number')
    p.add_argument('--xtb',default='/vast/yo73juc/miniconda3/envs/cresta/bin/xtb')
    p.add_argument('--orca',default='/work/AG_Presselt/orca_6_1_1_linux_x86-64_shared_openmpi418/orca')
    p.add_argument('--parser',type=Path,default=Path('/home/yo73juc/molcurator/extract_properties.py'))
    a=p.parse_args()
    rows=pd.read_csv(a.root/'molecules.csv')
    row=rows.iloc[a.index]
    name=str(row.molecule_id); smiles=str(row.smiles)
    folder=a.root/name
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'properties.csv').exists():
        print('Already parsed:',name,flush=True);return
    print(f'[{a.index+1}/{len(rows)}] {name} {smiles}',flush=True)
    mol=Chem.MolFromSmiles(smiles)
    if mol is None or Chem.GetFormalCharge(mol)!=0: raise ValueError('Invalid/nonneutral molecule')
    mol=Chem.AddHs(mol)
    params=AllChem.ETKDGv3();params.randomSeed=2026;params.numThreads=1
    if AllChem.EmbedMolecule(mol,params)!=0:raise RuntimeError('ETKDG failed')
    if AllChem.MMFFHasAllMoleculeParams(mol):
        AllChem.MMFFOptimizeMolecule(mol,maxIters=250)
    else:raise RuntimeError('MMFF parameters unavailable')
    xyz(mol,folder/'initial.xyz')
    execute([a.xtb,'initial.xyz','--gfn','2','--opt','normal','--chrg','0','--uhf','0'],folder,folder/'xtb.out')
    if not (folder/'xtbopt.xyz').exists():raise RuntimeError('xTB optimization XYZ missing')
    (folder/'excited.inp').write_text('''! PBE0 def2-SVP TightSCF
%elprop
 Dipole true
end
%tddft
 TDA true
 NRoots 5
end
%pal
 nprocs 1
end
%maxcore 2000
* xyzfile 0 1 xtbopt.xyz
''')
    execute([a.orca,str((folder/'excited.inp').resolve())],folder,folder/'excited.out')
    execute([sys.executable,str(a.parser.resolve()),'--xtb','xtb.out','--orca','excited.out','--smiles',smiles,'--id',name,'--out','properties.csv'],folder,folder/'parse.log')
    print('Finished:',name,flush=True)
if __name__=='__main__':main()
