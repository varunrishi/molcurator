#!/usr/bin/env python3
"""MolCurator conformer-aware workflow, neutral closed-shell molecules only.
RDKit ETKDG -> MMFF/UFF -> symmetry-aware RMSD clustering -> GFN2-xTB ->
post-xTB clustering -> ORCA TDA-PBE0/def2-SVP -> per-conformer CSV/JSON.
Run expensive step on an allocated compute node via SLURM.
"""
import argparse, csv, json, math, os, re, subprocess, sys, traceback
from pathlib import Path
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign
from extract_properties import parse_xtb, parse_orca

EH_TO_KCAL=627.509474

def xyz_from_mol(mol, conf_id, path):
    Chem.MolToXYZFile(mol, str(path), confId=conf_id)

def read_xyz_coords(path, natoms):
    lines=Path(path).read_text().splitlines()
    if int(lines[0].strip()) != natoms: raise ValueError('XYZ atom count mismatch')
    return [tuple(map(float, lines[i+2].split()[1:4])) for i in range(natoms)]

def structure_with_coords(template, coords):
    mol=Chem.Mol(template)
    mol.RemoveAllConformers()
    conf=Chem.Conformer(len(coords))
    for i, (x,y,z) in enumerate(coords): conf.SetAtomPosition(i,(x,y,z))
    mol.AddConformer(conf)
    return mol

def heavy_rms(a,b):
    # Explicit-H atom order is preserved by RDKit and xTB; remove H for speed.
    return rdMolAlign.GetBestRMS(Chem.RemoveHs(a), Chem.RemoveHs(b), maxMatches=10000)

def cluster_greedy(entries, rms_cutoff, energy_key):
    """Sorted lowest-energy-first; keep one representative per symmetry-aware RMSD cluster."""
    kept=[]
    for item in sorted(entries,key=lambda x:x[energy_key]):
        if all(heavy_rms(item['mol'],rep['mol']) >= rms_cutoff for rep in kept):
            kept.append(item)
    return kept

def generate(smiles,n,rms_cutoff,ff_window,seed):
    m=Chem.MolFromSmiles(smiles)
    if m is None: raise ValueError('Invalid SMILES')
    if Chem.GetFormalCharge(m)!=0 or any(a.GetNumRadicalElectrons() for a in m.GetAtoms()):
        raise ValueError('MVP accepts neutral closed-shell molecules only')
    m=Chem.AddHs(m)
    params=AllChem.ETKDGv3(); params.randomSeed=seed; params.numThreads=1; params.pruneRmsThresh=-1
    ids=list(AllChem.EmbedMultipleConfs(m,numConfs=n,params=params))
    if not ids: raise RuntimeError('No embedded conformers')
    if AllChem.MMFFHasAllMoleculeParams(m):
        ff='MMFF94'; results=AllChem.MMFFOptimizeMoleculeConfs(m,numThreads=1,mmffVariant='MMFF94',maxIters=500)
    else:
        ff='UFF'; results=AllChem.UFFOptimizeMoleculeConfs(m,numThreads=1,maxIters=500)
    candidates=[]
    for cid,(status,energy) in zip(ids,results):
        if status!=0 or not math.isfinite(energy): continue
        # Retain independent copy for each conformer, preserving coordinates.
        item=structure_with_coords(m,[tuple(m.GetConformer(cid).GetAtomPosition(i)) for i in range(m.GetNumAtoms())])
        candidates.append({'mol':item,'ff_energy_kcal':float(energy),'initial_conformer_id':int(cid)})
    if not candidates: raise RuntimeError('All force field optimizations failed')
    minimum=min(x['ff_energy_kcal'] for x in candidates)
    window=[x for x in candidates if x['ff_energy_kcal']-minimum <= ff_window]
    return ff, len(ids), len(candidates), cluster_greedy(window,rms_cutoff,'ff_energy_kcal')

def run_command(cmd,cwd,stdout_path,threads=1):
    env=os.environ.copy();env.update(OMP_NUM_THREADS=str(threads),OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with open(stdout_path,'w') as f:
        cp=subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env=env,check=False)
    return cp.returncode

def process(args):
    root=Path(args.out).resolve();root.mkdir(parents=True,exist_ok=True)
    summary={'molecule_id':args.id,'smiles':args.smiles,'status':'started'}
    def save(): (root/'summary.json').write_text(json.dumps(summary,indent=2,default=str))
    save()
    try:
        ff,embedded,optimized,reps=generate(args.smiles,args.nconfs,args.ff_rms,args.ff_window,args.seed)
        summary.update(force_field=ff,n_embedded=embedded,n_ff_optimized=optimized,n_ff_clusters=len(reps))
        reps=reps[:args.max_xtb]
        summary['n_xtb_attempted']=len(reps)
        save()
        xtb_results=[]
        for idx,item in enumerate(reps):
            sub=root/f'conf_{idx:03d}';sub.mkdir(exist_ok=True)
            xyz_from_mol(item['mol'],0,sub/'initial.xyz')
            rc=run_command([args.xtb,'initial.xyz','--gfn','2','--opt','normal','--chrg','0','--uhf','0'],sub,sub/'xtb.out')
            info={'id':idx,'ff_energy_kcal':item['ff_energy_kcal'],'ff_conformer_id':item['initial_conformer_id'],'xtb_exit_code':rc}
            text=(sub/'xtb.out').read_text(errors='replace')
            info.update(parse_xtb(text))
            if rc==0 and info.get('xtb_success') and (sub/'xtbopt.xyz').is_file() and info.get('xtb_energy_eh') is not None:
                try:
                    coords=read_xyz_coords(sub/'xtbopt.xyz',item['mol'].GetNumAtoms())
                    item2={'mol':structure_with_coords(item['mol'],coords),'xtb_energy_eh':info['xtb_energy_eh'],'folder':sub,'info':info}
                    xtb_results.append(item2)
                except Exception as e: info['xtb_geometry_error']=str(e)
            (sub/'xtb_properties.json').write_text(json.dumps(info,indent=2))
        summary['n_xtb_success']=len(xtb_results)
        if not xtb_results: raise RuntimeError('No successful xTB conformers')
        emin=min(c['xtb_energy_eh'] for c in xtb_results)
        window=[c for c in xtb_results if (c['xtb_energy_eh']-emin)*EH_TO_KCAL <= args.xtb_window]
        selected=cluster_greedy(window,args.xtb_rms,'xtb_energy_eh')[:args.max_orca]
        summary.update(n_xtb_clusters=len(cluster_greedy(window,args.xtb_rms,'xtb_energy_eh')),n_orca_selected=len(selected))
        save()
        rows=[]
        for rank,c in enumerate(selected):
            sub=c['folder'];info=dict(c['info'])
            inp=f'''! PBE0 def2-SVP TightSCF\n\n%elprop\n  Dipole true\nend\n\n%tddft\n  TDA true\n  NRoots {args.nroots}\nend\n\n%pal\n  nprocs 1\nend\n\n%maxcore 2000\n\n* xyzfile 0 1 xtbopt.xyz\n'''
            (sub/'excited.inp').write_text(inp)
            rc=run_command([args.orca,'excited.inp'],sub,sub/'excited.out')
            orca=parse_orca((sub/'excited.out').read_text(errors='replace'))
            row={'molecule_id':args.id,'smiles':args.smiles,'conformer_id':f'conf_{info["id"]:03d}',
                 'ff_method':ff,'ff_energy_kcal':info['ff_energy_kcal'],'xtb_relative_kcal':(c['xtb_energy_eh']-emin)*EH_TO_KCAL,
                 'geometry_path':str(sub/'xtbopt.xyz'),'orca_exit_code':rc,'orca_rank':rank}
            row.update({k:v for k,v in info.items() if k.startswith('xtb_')})
            row.update(orca)
            # Don't treat a merely terminated ORCA job as a complete excited-state label.
            row['label_valid']=bool(rc==0 and orca.get('orca_success') and isinstance(orca.get('s1_ev'),(int,float)))
            rows.append(row)
            (sub/'properties.json').write_text(json.dumps(row,indent=2))
        if rows:
            fields=sorted(set().union(*(r.keys() for r in rows)))
            with (root/'conformer_properties.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        summary['n_orca_success']=sum(r['label_valid'] for r in rows)
        summary['status']='complete' if summary['n_orca_success'] else 'no_valid_orca_labels'
    except Exception as e:
        summary['status']='failed';summary['error']=str(e)
        (root/'error_traceback.txt').write_text(traceback.format_exc())
    save()
    print(json.dumps(summary,indent=2))
    return 0 if summary['status']=='complete' else 1

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--smiles',required=True);p.add_argument('--id',required=True);p.add_argument('--out',required=True)
    p.add_argument('--xtb',default=os.environ.get('XTB_BIN','xtb'))
    p.add_argument('--orca',default=os.environ.get('ORCA_BIN','orca'))
    p.add_argument('--nconfs',type=int,default=30);p.add_argument('--ff-rms',type=float,default=0.25)
    p.add_argument('--ff-window',type=float,default=5.0);p.add_argument('--max-xtb',type=int,default=5)
    p.add_argument('--xtb-rms',type=float,default=0.25);p.add_argument('--xtb-window',type=float,default=5.0)
    p.add_argument('--max-orca',type=int,default=2);p.add_argument('--nroots',type=int,default=5)
    p.add_argument('--seed',type=int,default=42)
    a=p.parse_args()
    if min(a.nconfs,a.max_xtb,a.max_orca,a.nroots)<1: p.error('Counts must be positive')
    sys.exit(process(a))
if __name__=='__main__':main()
