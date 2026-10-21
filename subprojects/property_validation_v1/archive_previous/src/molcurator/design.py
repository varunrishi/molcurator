#!/usr/bin/env python3
"""Goal-directed small-molecule generation -> xTB screening -> frozen RF ranking -> ORCA verification.
Usage: python design.py generate|xtb|rank|orca|evaluate [--index N] [--target 4.5]
"""
import argparse, json, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdFingerprintGenerator, Descriptors
import joblib

# Configure through environment variables; no institute-specific paths committed.
BASE=Path(os.environ.get('MOLCURATOR_DATA_ROOT', './demo_data')).resolve()
MODEL=Path(os.environ.get('MOLCURATOR_MODEL_DIR', str(BASE/'ml276'))).resolve()
OUT=Path(os.environ.get('MOLCURATOR_DESIGN1_DIR', str(BASE/'design_qm9_0023'))).resolve()
SEED_ID=os.environ.get('MOLCURATOR_SEED_ID', 'qm9_0023')
FEATURES=['xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye']
XTB=os.environ.get('XTB_BIN','xtb')
ORCA=os.environ.get('ORCA_BIN','orca')
PARSER=Path(os.environ.get('MOLCURATOR_PARSER', str(Path(__file__).resolve().parents[2]/'legacy'/'extract_properties.py')))



def canonical(s):
    m=Chem.MolFromSmiles(str(s))
    return Chem.MolToSmiles(m,isomericSmiles=True) if m else None


def acceptable(m):
    if m is None or Chem.GetFormalCharge(m)!=0: return False
    if any(a.GetSymbol() not in ('C','N','O','F') for a in m.GetAtoms()):return False
    if not 2 <= m.GetNumHeavyAtoms() <= 9:return False
    if any(a.GetNumRadicalElectrons() for a in m.GetAtoms()):return False
    if any(a.GetIsotope() for a in m.GetAtoms()):return False
    # reject molecular fragments or SMILES with valence/ring issues
    if len(Chem.GetMolFrags(m))!=1:return False
    try:
        Chem.SanitizeMol(m)
        mm=Chem.AddHs(m)
        if not AllChem.MMFFHasAllMoleculeParams(mm):return False
    except Exception:return False
    return True


def proposal_moves(seed):
    """A reproducible enumerative one- and two-step local graph-edit neighborhood."""
    current={canonical(seed)}
    for depth in range(2):
        new=set()
        for smi in sorted(current):
            mol=Chem.MolFromSmiles(smi)
            if mol is None:continue
            for a in mol.GetAtoms():
                i=a.GetIdx(); element=a.GetSymbol()
                if element in ('C','N','O','F'):
                    # neutral atom substitutions; RDKit sanitation rejects impossible valence
                    for replacement in ('C','N','O','F'):
                        if replacement==element:continue
                        rw=Chem.RWMol(mol)
                        rw.GetAtomWithIdx(i).SetAtomicNum({'C':6,'N':7,'O':8,'F':9}[replacement])
                        # reset explicit hydrogens and formal charges
                        rw.GetAtomWithIdx(i).SetFormalCharge(0)
                        rw.GetAtomWithIdx(i).SetNumExplicitHs(0)
                        rw.GetAtomWithIdx(i).SetNoImplicit(False)
                        try:
                            candidate=rw.GetMol();Chem.SanitizeMol(candidate)
                            if acceptable(candidate):new.add(Chem.MolToSmiles(candidate,isomericSmiles=True))
                        except Exception:pass
                if mol.GetNumHeavyAtoms()<9 and element not in ('F',):
                    for sym in ('C','N','O','F'):
                        rw=Chem.RWMol(mol)
                        j=rw.AddAtom(Chem.Atom(sym))
                        rw.AddBond(i,j,Chem.BondType.SINGLE)
                        try:
                            candidate=rw.GetMol();Chem.SanitizeMol(candidate)
                            if acceptable(candidate):new.add(Chem.MolToSmiles(candidate,isomericSmiles=True))
                        except Exception:pass
                # prune terminal atoms (may change connectivity, but stay local)
                if a.GetDegree()==1 and mol.GetNumHeavyAtoms()>2:
                    rw=Chem.RWMol(mol);rw.RemoveAtom(i)
                    try:
                        candidate=rw.GetMol();Chem.SanitizeMol(candidate)
                        if acceptable(candidate):new.add(Chem.MolToSmiles(candidate,isomericSmiles=True))
                    except Exception:pass
        current |= new
        print('Generation depth', depth+1,'candidate structures',len(current),flush=True)
        if len(current)>25000:
            # preserve reproducibility; stop to avoid combinatorial explosion
            break
    return current


def generate(args):
    OUT.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(BASE/'qm9_100'/'molecules.csv')
    hits=df[df.molecule_id.astype(str)==SEED_ID]
    if len(hits)!=1:raise SystemExit(f'Could not uniquely identify {SEED_ID} in qm9_100/molecules.csv')
    seed=canonical(hits.iloc[0]['smiles'])
    assert seed is not None
    if not acceptable(Chem.MolFromSmiles(seed)):
        raise SystemExit('Seed outside neutral C/N/O/F <=9 heavy-atom domain. Review chemistry constraints.')
    seen=set()
    for p in [MODEL/'ml_dataset.csv',BASE/'external_test50'/'molecules.csv']:
        if p.exists():
            d=pd.read_csv(p)
            if 'smiles' in d:
                seen |= {x for x in (canonical(s) for s in d.smiles) if x}
    proposed=proposal_moves(seed)
    fpgen=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=1024)
    seed_fp=fpgen.GetFingerprint(Chem.MolFromSmiles(seed))
    scored=[]
    for s in proposed:
        if s in seen or s==seed:continue
        m=Chem.MolFromSmiles(s)
        sim=DataStructs.TanimotoSimilarity(seed_fp,fpgen.GetFingerprint(m))
        scored.append((s,sim,m.GetNumHeavyAtoms()))
    # preserve similarity/diversity across candidates; randomized tie-breaks reproducible
    scored.sort(key=lambda x:(-x[1],x[0]))
    pool=[r for r in scored if r[1]>=args.min_similarity]
    if len(pool)<args.count:
        print(f'Only {len(pool)} novel structures >= similarity {args.min_similarity}; selecting them all.',flush=True)
    rng=np.random.default_rng(2026)
    # sampling weighted by similarity to avoid only picking near-identical structural variants
    if len(pool)>args.count:
        weights=np.array([max(0.05,r[1]) for r in pool],float);weights/=weights.sum()
        ids=rng.choice(len(pool),size=args.count,replace=False,p=weights)
        selected=[pool[i] for i in ids]
    else:selected=pool
    selected.sort(key=lambda x:(-x[1],x[0]))
    result=pd.DataFrame([{'molecule_id':f'design_{i:04d}','smiles':s,'similarity_to_seed':sim,'heavy_atoms':n}
                         for i,(s,sim,n) in enumerate(selected,1)])
    if result.empty:raise SystemExit('No valid novel candidates. Lower --min-similarity or inspect seed.')
    result.to_csv(OUT/'molecules.csv',index=False)
    (OUT/'design_spec.json').write_text(json.dumps({'seed_id':SEED_ID,'seed_smiles':seed,'target_s1_ev':args.target,
        'generation':'1- and 2-step neutral graph edits over C,N,O,F, up to 9 heavy atoms',
        'selected_count':len(result),'note':'New graph structures are chemically sanitized, not guaranteed stable or synthesizable.'},indent=2))
    print('SEED',seed,'generated',len(proposed),'unique candidate structures; selected',len(result),flush=True)
    print('OUTPUT',OUT/'molecules.csv',flush=True)
    print('SUBMIT: sbatch --array=0-'+str(len(result)-1)+'%8 /home/yo73juc/molcurator/molcurator_design/xtb_array.sbatch',flush=True)


def xyz(m,path):
    c=m.GetConformer()
    with path.open('w') as f:
        f.write(f'{m.GetNumAtoms()}\nRDKit ETKDG/MMFF94\n')
        for a in m.GetAtoms():
            p=c.GetAtomPosition(a.GetIdx());f.write(f'{a.GetSymbol()} {p.x:.9f} {p.y:.9f} {p.z:.9f}\n')


def execute(cmd,cwd,log):
    with log.open('w') as f:
        p=subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError(f'Exit={p.returncode} on {cmd}, log={log}')


def xtb(args):
    df=pd.read_csv(OUT/'molecules.csv');row=df.iloc[args.index]
    smi=str(row.smiles);name=str(row.molecule_id);wd=OUT/name;wd.mkdir(exist_ok=True)
    if (wd/'xtbopt.xyz').exists() and (wd/'xtb.out').exists():
        print('Already xTB optimized',name);return
    mol=Chem.AddHs(Chem.MolFromSmiles(smi));params=AllChem.ETKDGv3();params.randomSeed=2026+args.index;params.numThreads=1
    if AllChem.EmbedMolecule(mol,params)!=0:raise RuntimeError('Embedding failed '+name)
    if AllChem.MMFFOptimizeMolecule(mol,maxIters=250)<0:raise RuntimeError('MMFF failed '+name)
    xyz(mol,wd/'initial.xyz')
    execute([XTB,'initial.xyz','--gfn','2','--opt','normal','--chrg','0','--uhf','0'],wd,wd/'xtb.out')
    if not (wd/'xtbopt.xyz').exists():raise RuntimeError('xtbopt.xyz missing for '+name)
    print('xTB done',name,flush=True)


def parse_xtb_with_existing_parser(name,smiles):
    wd=OUT/name
    # Existing parser expects ORCA; perform a lightweight ORCA-independent parse of xTB log.
    import re
    text=(wd/'xtb.out').read_text(errors='replace')
    # xTB orbital details are printed with HOMO/LUMO lines: use xTB output carefully
    homo=lumo=gap=dip=None
    for ln in text.splitlines():
        if '(HOMO)' in ln:
            m=re.search(r'(-?\d+\.\d+)\s*\(HOMO\)',ln)
            if m:homo=float(m.group(1))
        if '(LUMO)' in ln:
            m=re.search(r'(-?\d+\.\d+)\s*\(LUMO\)',ln)
            if m:lumo=float(m.group(1))
        if 'HOMO-LUMO GAP' in ln.upper():
            m=re.search(r'HOMO-LUMO GAP\s+([0-9.]+)\s*eV',ln,re.I)
            if m:gap=float(m.group(1))
        if 'molecular dipole' in ln.lower():pass
    # Preferred: parse via matching methods from official existing project parser if possible;
    # xTB output format varies; compare sampled values against existing single-conformer CSVs.
    # Dipole: xTB prints a total vector at the end of a molecular dipole block.
    lines=text.splitlines()
    for i,ln in enumerate(lines):
        if 'molecular dipole:' in ln.lower():
            for near in lines[i+1:i+9]:
                if 'full:' in near.lower():
                    parts=near.split()
                    try:dip=float(parts[-1])
                    except (ValueError,IndexError):pass
                    break
    if gap is None and homo is not None and lumo is not None:gap=lumo-homo
    return {FEATURES[0]:homo,FEATURES[1]:lumo,FEATURES[2]:gap,FEATURES[3]:dip}


def rank(args):
    df=pd.read_csv(OUT/'molecules.csv')
    rows=[]
    for _,row in df.iterrows():
        name=str(row.molecule_id);p=OUT/name/'xtb.out'
        if not p.exists() or not (OUT/name/'xtbopt.xyz').exists():continue
        prop=parse_xtb_with_existing_parser(name,row.smiles)
        rows.append({**row.to_dict(),**prop})
    if not rows:raise SystemExit('No completed xTB results')
    pool=pd.DataFrame(rows)
    pool.to_csv(OUT/'xtb_candidate_features.csv',index=False)
    # avoid silently giving the RF wrong units / missing feature data
    valid=pool[pool[FEATURES].notna().all(axis=1)].copy()
    if valid.empty:raise SystemExit('Could not parse full xTB descriptors. Inspect xtb.out vs ml276/ml_dataset.csv before ranking.')
    train=pd.read_csv(MODEL/'ml_dataset.csv')
    for col in FEATURES:
        lo,hi=np.nanpercentile(pd.to_numeric(train[col],errors='coerce'),[1,99])
        print(f'{col:24s} training 1%-99%: {lo:9.3f} to {hi:9.3f} ; candidates: {valid[col].min():9.3f} to {valid[col].max():9.3f}',flush=True)
    # Check consistency: gap ≈ LUMO-HOMO for eV orbital values
    discrepancy=np.abs(valid.xtb_gap_ev-(valid.xtb_lumo_ev-valid.xtb_homo_ev))
    if (discrepancy>0.4).mean()>0.2:
        raise SystemExit('xTB frontier orbital parse inconsistent: inspect log before trusting predictions')
    fpgen=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=1024)
    fingerprints=[]
    for smi in valid.smiles:
        a=np.zeros(1024,dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fpgen.GetFingerprint(Chem.MolFromSmiles(smi)),a)
        fingerprints.append(a)
    x=np.column_stack([np.stack(fingerprints),valid[FEATURES].to_numpy(float)])
    rf=joblib.load(MODEL/'combined_rf.joblib')
    if hasattr(rf,'n_features_in_') and rf.n_features_in_!=1028:
        raise SystemExit(f'Unexpected pretrained model feature count {rf.n_features_in_}')
    valid['predicted_s1_ev']=rf.predict(x)
    valid['abs_target_error_ev']=(valid.predicted_s1_ev-args.target).abs()
    valid['outside_xtb_training_1_99pct']=False
    for col in FEATURES:
        lo,hi=np.nanpercentile(pd.to_numeric(train[col],errors='coerce'),[1,99])
        valid['outside_xtb_training_1_99pct'] |= ~valid[col].between(lo,hi)
    valid=valid.sort_values(['abs_target_error_ev','similarity_to_seed']).reset_index(drop=True)
    valid.to_csv(OUT/'ranked_candidates.csv',index=False)
    # Diversity-aware greedy selection: avoid near-duplicate molecules among the top targets
    chosen=[];chosen_fp=[]
    for _,row in valid.iterrows():
        if len(chosen)>=args.top:break
        mol=Chem.MolFromSmiles(row.smiles);f=fpgen.GetFingerprint(mol)
        if all(DataStructs.TanimotoSimilarity(f,old)<0.9 for old in chosen_fp):
            chosen.append(row);chosen_fp.append(f)
    top=pd.DataFrame(chosen)
    top.to_csv(OUT/'orca_selected.csv',index=False)
    print('\nTop selected:\n',top[['molecule_id','smiles','predicted_s1_ev','abs_target_error_ev','similarity_to_seed','outside_xtb_training_1_99pct']].to_string(index=False),flush=True)
    print('xTB completed:',len(pool),'fully parsed:',len(valid),'ORCA selected:',len(top),flush=True)
    print('WARNING: Predicted within tolerance is NOT validated until ORCA QC is finished.',flush=True)


def orca(args):
    df=pd.read_csv(OUT/'orca_selected.csv');row=df.iloc[args.index];name=str(row.molecule_id)
    wd=OUT/name
    if (wd/'properties.csv').exists():print('Already ORCA parsed',name);return
    if not (wd/'xtbopt.xyz').exists():raise SystemExit(f'Missing xTB geometry {name}')
    (wd/'excited.inp').write_text('''! PBE0 def2-SVP TightSCF
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
    if not (wd/'excited.out').exists():
        execute([ORCA,str((wd/'excited.inp').resolve())],wd,wd/'excited.out')
    execute([sys.executable,str(PARSER),'--xtb','xtb.out','--orca','excited.out',
             '--smiles',str(row.smiles),'--id',name,'--out','properties.csv'],wd,wd/'parse.log')
    print('ORCA done',name,flush=True)


def evaluate(args):
    selection=pd.read_csv(OUT/'orca_selected.csv')
    rows=[]
    for _,row in selection.iterrows():
        p=OUT/str(row.molecule_id)/'properties.csv'
        if not p.exists():continue
        q=pd.read_csv(p)
        if len(q)!=1:continue
        q=q.iloc[0]
        if str(q.get('orca_success','')).lower() not in ('true','1') or pd.isna(q.get('s1_ev')):continue
        rows.append({'molecule_id':row.molecule_id,'smiles':row.smiles,
                     'predicted_s1_ev':row.predicted_s1_ev,'orca_s1_ev':float(q.s1_ev),
                     'target_s1_ev':args.target,'target_error_ev':abs(float(q.s1_ev)-args.target),
                     'prediction_error_ev':float(q.s1_ev)-float(row.predicted_s1_ev),
                     'oscillator_strength':q.get('s1_oscillator_strength',np.nan),
                     'similarity_to_seed':row.similarity_to_seed})
    if not rows:raise SystemExit('No successful ORCA validation results yet')
    results=pd.DataFrame(rows).sort_values('target_error_ev')
    results.to_csv(OUT/'validated_designs.csv',index=False)
    print(results.to_string(index=False,float_format=lambda x:f'{x:.4f}'))
    print(f'ORCA-validated: {len(results)}/{len(selection)}; target within ±0.2 eV: {(results.target_error_ev<=0.2).sum()}',flush=True)
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(7,6))
        ax.scatter(results.predicted_s1_ev,results.orca_s1_ev,s=60)
        lo=min(results.predicted_s1_ev.min(),results.orca_s1_ev.min(),args.target)-.2
        hi=max(results.predicted_s1_ev.max(),results.orca_s1_ev.max(),args.target)+.2
        ax.plot([lo,hi],[lo,hi],'--',color='gray')
        ax.axhline(args.target,linestyle=':',color='black',label='Target S1')
        ax.set(xlabel='RF-predicted S1 (eV)',ylabel='ORCA-validated S1 (eV)',title='Goal-directed MolCurator: selected candidates')
        ax.legend();fig.tight_layout();fig.savefig(OUT/'targeted_generation_validation.png',dpi=250);plt.close(fig)
        fig,ax=plt.subplots(figsize=(8,4))
        labels=results.molecule_id.astype(str).tolist(); pos=np.arange(len(labels))
        ax.bar(pos-.18,results.predicted_s1_ev,width=.36,label='Predicted')
        ax.bar(pos+.18,results.orca_s1_ev,width=.36,label='ORCA')
        ax.axhline(args.target,linestyle='--',color='black',label='Target')
        ax.set_xticks(pos,labels,rotation=45,ha='right');ax.set_ylabel('S1 (eV)');ax.legend()
        fig.tight_layout();fig.savefig(OUT/'candidate_target_comparison.png',dpi=250);plt.close(fig)
    except ImportError:print('Matplotlib missing: CSV generated without plots')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['generate','xtb','rank','orca','evaluate'])
    p.add_argument('--index',type=int)
    p.add_argument('--count',type=int,default=200)
    p.add_argument('--top',type=int,default=8)
    p.add_argument('--target',type=float,default=4.5)
    p.add_argument('--min-similarity',type=float,default=.25)
    args=p.parse_args()
    if args.command in ('xtb','orca') and args.index is None:p.error('--index required')
    globals()[args.command](args)
if __name__=='__main__':main()
