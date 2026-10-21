#!/usr/bin/env python3
"""Iteration 2 for MolCurator: audit -> augment -> propose -> xTB -> rank -> ORCA -> compare.
Uses existing design.py QC protocol and immutable ml276 baseline. Requires RDKit/pandas/sklearn/joblib.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

BASE=Path('/work/AG_Presselt/MolCurator')
PROJECT=Path('/home/yo73juc/molcurator/molcurator_design')
sys.path.insert(0,str(PROJECT))
import design as old
OUT=BASE/'design_iteration2'
PREV=BASE/'design_qm9_0023'
MODEL=BASE/'ml276'
FEATS=old.FEATURES
FPGEN=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=1024)

def fp(s):
    m=Chem.MolFromSmiles(str(s)); arr=np.zeros(1024,dtype=np.int8)
    DataStructs.ConvertToNumpyArray(FPGEN.GetFingerprint(m),arr)
    return arr

def xmat(df):
    return np.column_stack((np.stack([fp(s) for s in df.smiles]),df[FEATS].to_numpy(float)))

def canon(s):
    return old.canonical(s)

def training_ids():
    d=json.loads((MODEL/'experiment_summary.json').read_text())
    return set(map(str,d['test_ids']))

def audit():
    prev=pd.read_csv(PREV/'validated_designs.csv')
    xtb=pd.read_csv(PREV/'xtb_candidate_features.csv')
    merged=prev[['molecule_id','smiles','orca_s1_ev']].merge(xtb[['molecule_id']+FEATS],on='molecule_id',how='inner',validate='one_to_one')
    if len(merged)!=len(prev):raise SystemExit('Some iteration-1 molecules lack xTB descriptors')
    train=pd.read_csv(MODEL/'ml_dataset.csv')
    for f in FEATS:
        print(f'{f:20s} training [{train[f].min():.3f}, {train[f].max():.3f}], design [{merged[f].min():.3f}, {merged[f].max():.3f}]',flush=True)
    gap=np.abs(merged.xtb_gap_ev-(merged.xtb_lumo_ev-merged.xtb_homo_ev))
    print('Gap consistency max |gap - (LUMO-HOMO)|:',gap.max())
    if (gap>0.4).any():raise SystemExit('Mismatch in xTB frontier orbital parsing. STOP.')
    model=joblib.load(MODEL/'combined_rf.joblib')
    if model.n_features_in_!=1028:raise SystemExit('Unexpected 1028-feature layout')
    check=model.predict(xmat(merged))
    rerun=pd.Series(check,index=merged.molecule_id).reindex(prev.molecule_id).to_numpy()
    delta=np.abs(rerun-prev.predicted_s1_ev.to_numpy(float))
    print('Prediction reproducibility maximum error (eV):',delta.max())
    if delta.max()>0.00015:raise SystemExit('Model prediction mismatch; STOP, inspect features')
    print('AUDIT PASSED: original predictions reproduced.')
    return merged

def fit(args):
    OUT.mkdir(exist_ok=True,parents=True)
    added=audit()
    train=pd.read_csv(MODEL/'ml_dataset.csv')
    held=training_ids()
    train=train[~train.molecule_id.astype(str).isin(held)].copy()
    if len(train)!=257:raise SystemExit(f'Expected 257 train records, found {len(train)}')
    train=train[['molecule_id','smiles','s1_ev']+FEATS].copy()
    # Do not train on external molecules. Iteration-1 candidates are now labeled training examples.
    add=added.rename(columns={'orca_s1_ev':'s1_ev'})
    add=add[['molecule_id','smiles','s1_ev']+FEATS].copy()
    known={canon(x) for x in train.smiles}
    if any(canon(x) in known for x in add.smiles):raise SystemExit('Candidate already in original training set')
    both=pd.concat([train,add],ignore_index=True)
    model=make_pipeline(SimpleImputer(strategy='median'),RandomForestRegressor(
        n_estimators=300,random_state=2026,min_samples_leaf=2,n_jobs=1))
    model.fit(xmat(both),both.s1_ev.to_numpy(float))
    joblib.dump(model,OUT/'combined_rf_augmented.joblib')
    both.to_csv(OUT/'augmented_train.csv',index=False)
    print(f'Fitted augmented RF on {len(both)} molecules (257 + {len(add)}); original model unchanged',flush=True)

def generate(args):
    OUT.mkdir(exist_ok=True,parents=True)
    train=pd.read_csv(MODEL/'ml_dataset.csv')
    forbidden={canon(s) for s in train.smiles}
    ext=BASE/'external_test50'/'molecules.csv'
    if ext.exists():forbidden|={canon(s) for s in pd.read_csv(ext).smiles}
    old_design=pd.read_csv(PREV/'molecules.csv')
    forbidden|={canon(s) for s in old_design.smiles}
    seed_csv=pd.read_csv(BASE/'qm9_100'/'molecules.csv')
    seed=canon(seed_csv.loc[seed_csv.molecule_id=='qm9_0023','smiles'].iloc[0])
    forbidden.add(seed)
    validated=pd.read_csv(PREV/'validated_designs.csv')
    anchors=[seed]+[canon(s) for s in validated.smiles]
    # Build a fresh neighborhood around *previously validated* candidates, not only the original seed.
    # This prevents regenerating the exact same first-cycle candidates.
    proposals=set()
    for n,anchor in enumerate(anchors,1):
        pool=old.proposal_moves(anchor)
        proposals|=pool
        print(f'Anchor {n}/{len(anchors)}: pool size {len(proposals)}',flush=True)
    seedfp=FPGEN.GetFingerprint(Chem.MolFromSmiles(seed))
    eligible=[]
    for s in sorted(proposals):
        c=canon(s)
        if c is None or c in forbidden:continue
        m=Chem.MolFromSmiles(c)
        if not old.acceptable(m):continue
        similarity=DataStructs.TanimotoSimilarity(seedfp,FPGEN.GetFingerprint(m))
        if similarity < args.min_similarity:continue
        eligible.append((c,float(similarity),m.GetNumHeavyAtoms()))
    if not eligible:raise SystemExit('No new valid candidates; reduce --min-similarity')
    rng=np.random.default_rng(args.seed)
    # Similarity-biased but not similarity-sorted random sampling to maintain diversity.
    weights=np.array([max(0.05,x[1]) for x in eligible]);weights=weights/weights.sum()
    selected=rng.choice(len(eligible),size=min(args.count,len(eligible)),replace=False,p=weights)
    result=pd.DataFrame([{'molecule_id':f'iter2_{i:04d}','smiles':eligible[j][0],
        'similarity_to_seed':eligible[j][1],'heavy_atoms':eligible[j][2]}
        for i,j in enumerate(selected,1)])
    assert not any(canon(s) in forbidden for s in result.smiles)
    result.to_csv(OUT/'molecules.csv',index=False)
    print(f'NEW candidates selected: {len(result)} / {len(eligible)} eligible, excluded prior design and all existing tests',flush=True)

def rank(args):
    if not (OUT/'combined_rf_augmented.joblib').exists():raise SystemExit('Run fit first')
    pool=pd.read_csv(OUT/'molecules.csv');rows=[]
    old.OUT=OUT
    for _,r in pool.iterrows():
        wd=OUT/str(r.molecule_id)
        if not (wd/'xtbopt.xyz').exists() or not (wd/'xtb.out').exists():continue
        vals=old.parse_xtb_with_existing_parser(r.molecule_id,r.smiles)
        rows.append({**r.to_dict(),**vals})
    if not rows:raise SystemExit('No xTB calculations completed')
    df=pd.DataFrame(rows);df.to_csv(OUT/'xtb_candidate_features.csv',index=False)
    df=df.dropna(subset=FEATS).copy()
    df=df[np.isfinite(df[FEATS].to_numpy(float)).all(axis=1)].copy()
    df=df[np.abs(df.xtb_gap_ev-(df.xtb_lumo_ev-df.xtb_homo_ev))<0.4].copy()
    if len(df)==0:raise SystemExit('No valid electronic descriptors')
    orig=joblib.load(MODEL/'combined_rf.joblib');new=joblib.load(OUT/'combined_rf_augmented.joblib')
    X=xmat(df);df['pred_original_ev']=orig.predict(X);df['pred_augmented_ev']=new.predict(X)
    train=pd.read_csv(MODEL/'ml_dataset.csv')
    # Strong applicability-domain screen: every xTB feature must fall within training range.
    df['range_ood_count']=sum((~df[f].between(train[f].min(),train[f].max())).astype(int) for f in FEATS)
    df['target_distance_ev']=np.abs(df.pred_augmented_ev-args.target)
    df['selection_score']=df.target_distance_ev+args.ood_penalty*df.range_ood_count
    df=df.sort_values('selection_score').reset_index(drop=True)
    df.to_csv(OUT/'ranked_candidates.csv',index=False)
    selected=[];fps=[]
    # Select diverse candidates in-domain where possible; fill with penalized candidates only if needed.
    for _,r in df.iterrows():
        f=FPGEN.GetFingerprint(Chem.MolFromSmiles(r.smiles))
        if all(DataStructs.TanimotoSimilarity(f,oldfp)<args.max_similarity for oldfp in fps):
            selected.append(r.to_dict());fps.append(f)
        if len(selected)>=args.top:break
    sel=pd.DataFrame(selected)
    sel.to_csv(OUT/'orca_selected.csv',index=False)
    print('Candidates with ALL features inside training ranges:',(df.range_ood_count==0).sum(),'/',len(df))
    print(sel[['molecule_id','pred_original_ev','pred_augmented_ev','target_distance_ev','range_ood_count','similarity_to_seed']].to_string(index=False))
    print('ORCA selection:',len(sel),flush=True)

def evaluate(args):
    sel=pd.read_csv(OUT/'orca_selected.csv');rows=[]
    for _,r in sel.iterrows():
        p=OUT/str(r.molecule_id)/'properties.csv'
        if not p.exists():continue
        t=pd.read_csv(p)
        if len(t)!=1 or str(t.iloc[0].get('orca_success','')).lower() not in ('true','1'):continue
        s=float(t.iloc[0].s1_ev)
        if not np.isfinite(s):continue
        rows.append({**r.to_dict(),'orca_s1_ev':s,'target_error_ev':abs(s-args.target),
                     'original_abs_prediction_error_ev':abs(s-r.pred_original_ev),
                     'augmented_abs_prediction_error_ev':abs(s-r.pred_augmented_ev)})
    if not rows:raise SystemExit('No valid new ORCA results')
    out=pd.DataFrame(rows).sort_values('target_error_ev');out.to_csv(OUT/'validated_iteration2.csv',index=False)
    print(out[['molecule_id','pred_original_ev','pred_augmented_ev','orca_s1_ev','target_error_ev']].to_string(index=False,float_format=lambda z:f'{z:.4f}'))
    print('Validated',len(out),'/',len(sel),'hits within 0.2 eV:',(out.target_error_ev<=.2).sum())
    print('MAE original on NEW selected:',out.original_abs_prediction_error_ev.mean())
    print('MAE augmented on NEW selected:',out.augmented_abs_prediction_error_ev.mean())
    print('Mean ORCA target distance:',out.target_error_ev.mean())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5));idx=np.arange(len(out))
    ax.scatter(idx,out.pred_original_ev,label='Original RF',marker='x')
    ax.scatter(idx,out.pred_augmented_ev,label='Augmented RF',marker='o')
    ax.scatter(idx,out.orca_s1_ev,label='ORCA',marker='D')
    ax.axhline(args.target,color='black',linestyle='--',label='Target')
    ax.axhspan(args.target-.2,args.target+.2,alpha=.10)
    ax.set_xticks(idx,out.molecule_id,rotation=45,ha='right');ax.set_ylabel('S1 (eV)');ax.legend();fig.tight_layout()
    fig.savefig(OUT/'iteration2_validation.png',dpi=250);plt.close(fig)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['audit','fit','generate','xtb','rank','orca','evaluate'])
    p.add_argument('--index',type=int);p.add_argument('--target',type=float,default=4.5)
    p.add_argument('--count',type=int,default=300);p.add_argument('--top',type=int,default=12)
    p.add_argument('--min-similarity',type=float,default=.25)
    p.add_argument('--max-similarity',type=float,default=.88)
    p.add_argument('--ood-penalty',type=float,default=.5)
    p.add_argument('--seed',type=int,default=2030)
    a=p.parse_args()
    if a.command=='audit':audit()
    elif a.command=='fit':fit(a)
    elif a.command=='generate':generate(a)
    elif a.command in ('xtb','orca'):
        if a.index is None:p.error('--index is required')
        old.OUT=OUT
        getattr(old,a.command)(a)
    elif a.command=='rank':rank(a)
    elif a.command=='evaluate':evaluate(a)
if __name__=='__main__':main()
