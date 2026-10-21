#!/usr/bin/env python3
"""Paired xTB/ORCA HOMO-LUMO and ground-state dipole benchmark.

Uses the original QM9 frozen IDs, never fits on their molecules, and keeps
external/generated validation data out of training. ORCA results are on xTB geometries.
"""
import argparse
import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

DESC = ['xtb_homo_ev', 'xtb_lumo_ev', 'xtb_gap_ev', 'xtb_dipole_debye']
PAIRS = [('gap_ev', 'xtb_gap_ev', 'orca_gap_ev', 'eV'),
         ('dipole_debye', 'xtb_dipole_debye', 'orca_dipole_debye', 'D'),
         ('homo_ev', 'xtb_homo_ev', 'orca_homo_ev', 'eV'),
         ('lumo_ev', 'xtb_lumo_ev', 'orca_lumo_ev', 'eV')]


def metrics(y, p):
    return dict(mae=float(mean_absolute_error(y, p)),
                rmse=float(np.sqrt(mean_squared_error(y, p))),
                bias=float(np.mean(p-y)),
                r2=float(r2_score(y, p)) if len(y) >= 2 else None)


def plot_parity(y, p, title, output, units):
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.scatter(y, p, s=28, alpha=.75)
    lo, hi = min(np.min(y), np.min(p)), max(np.max(y), np.max(p))
    spread = max(hi-lo, .01)
    ax.plot([lo-.04*spread, hi+.04*spread], [lo-.04*spread, hi+.04*spread], '--', color='gray')
    ax.set(xlabel=f'ORCA reference ({units})', ylabel=f'Prediction ({units})', title=title)
    ax.text(.03, .97, f'MAE = {mean_absolute_error(y,p):.3f} {units}\nN = {len(y)}',
            transform=ax.transAxes, va='top', bbox={'facecolor':'white','alpha':.88,'edgecolor':'lightgray'})
    fig.tight_layout(); fig.savefig(output, dpi=220); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=Path('/work/AG_Presselt/MolCurator/ml276/ml_dataset.csv'))
    ap.add_argument('--frozen', type=Path, default=Path('/work/AG_Presselt/MolCurator/qm9_100/baseline94/frozen_test_ids.csv'))
    ap.add_argument('--out', type=Path, default=Path('/work/AG_Presselt/MolCurator/multifidelity_benchmark'))
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.data)
    ids = pd.read_csv(args.frozen)['molecule_id'].astype(str).tolist()
    if len(ids) != 19 or len(set(ids)) != 19:
        raise ValueError('Expected 19 unique frozen test molecule IDs')
    required = {'molecule_id','smiles',*DESC,*(x for _,a,b,_ in PAIRS for x in (a,b))}
    missing = sorted(required.difference(df.columns))
    if missing: raise ValueError(f'Missing columns: {missing}')
    df['molecule_id'] = df['molecule_id'].astype(str)
    for x in set(DESC + [x for _,a,b,_ in PAIRS for x in (a,b)]):
        df[x] = pd.to_numeric(df[x], errors='coerce')
    df = df.replace([np.inf, -np.inf], np.nan)
    if df.molecule_id.duplicated().any():
        raise ValueError('Duplicate molecule IDs in input; curate before running')
    df['canonical_smiles'] = [Chem.MolToSmiles(m, isomericSmiles=True) if m else None
                              for m in (Chem.MolFromSmiles(str(s)) for s in df.smiles)]
    if df.canonical_smiles.isna().any():
        raise ValueError('Invalid SMILES in input; curate before running')
    test_all = df[df.molecule_id.isin(ids)].copy()
    if len(test_all) != 19: raise ValueError(f'Found {len(test_all)} of 19 frozen test IDs')
    test_smiles = set(test_all.canonical_smiles)
    train_all = df[~df.molecule_id.isin(ids) & ~df.canonical_smiles.isin(test_smiles)].copy()
    if set(train_all.canonical_smiles).intersection(test_smiles):
        raise ValueError('Molecular leakage into train')
    print('Frozen split:',len(train_all),'train /',len(test_all),'test',flush=True)
    fpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    def fingerprint(smiles):
        arr = np.zeros(1024, dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fpgen.GetFingerprint(Chem.MolFromSmiles(smiles)), arr)
        return arr
    fps = {s:fingerprint(s) for s in df.canonical_smiles.unique()}
    metrics_rows=[]; pred_rows=[]; qc=[]; models={}
    for target, cheap, reference, units in PAIRS:
        # Identical paired-coverage across methods for this target.
        cols = list(set(DESC + [cheap, reference]))
        train = train_all.dropna(subset=cols).copy()
        test = test_all.dropna(subset=cols).copy()
        if len(train)<20 or len(test)<5:
            print(f'SKIP {target}: only {len(train)} train, {len(test)} test complete pairs')
            continue
        print(f'\n{target}: paired train={len(train)}, paired frozen test={len(test)}',flush=True)
        for stage, frame in [('train',train),('test',test)]:
            gap_check = (frame['xtb_lumo_ev']-frame['xtb_homo_ev']-frame['xtb_gap_ev']).abs()
            gap_orca = (frame['orca_lumo_ev']-frame['orca_homo_ev']-frame['orca_gap_ev']).abs()
            qc.append({'target':target,'set':stage,'n':len(frame),
                       'xtb_gap_max_consistency_ev':float(gap_check.max()),
                       'orca_gap_max_consistency_ev':float(gap_orca.max()),
                       'mean_delta':float((frame[reference]-frame[cheap]).mean()),
                       'std_delta':float((frame[reference]-frame[cheap]).std())})
        Xfp_train=np.stack([fps[s] for s in train.canonical_smiles]); Xfp_test=np.stack([fps[s] for s in test.canonical_smiles])
        Xxtb_train=train[DESC].to_numpy(float); Xxtb_test=test[DESC].to_numpy(float)
        Xhy_train=np.column_stack((Xfp_train,Xxtb_train)); Xhy_test=np.column_stack((Xfp_test,Xxtb_test))
        yt=train[reference].to_numpy(float); y=test[reference].to_numpy(float)
        base_train=train[cheap].to_numpy(float); base_test=test[cheap].to_numpy(float)
        corr_train=yt-base_train
        rf = lambda: RandomForestRegressor(n_estimators=300,min_samples_leaf=2,random_state=args.seed,n_jobs=4)
        specs = [('raw_xtb',None,None,None),
                 ('constant_delta',None,None,None),
                 ('linear_calibration',make_pipeline(StandardScaler(),Ridge(alpha=1.0)),Xxtb_train,Xxtb_test),
                 ('smiles_rf',rf(),Xfp_train,Xfp_test),
                 ('xtb_rf',rf(),Xxtb_train,Xxtb_test),
                 ('hybrid_rf',rf(),Xhy_train,Xhy_test),
                 ('delta_rf',rf(),Xhy_train,Xhy_test)]
        for name, model, xx, xx_test in specs:
            if name=='raw_xtb': prediction=base_test.copy()
            elif name=='constant_delta': prediction=base_test + np.mean(corr_train)
            else:
                yfit = corr_train if name=='delta_rf' else yt
                model.fit(xx, yfit)
                prediction=model.predict(xx_test)
                if name=='delta_rf': prediction=base_test+prediction
                joblib.dump(model,args.out/f'{target}_{name}.joblib')
            score=metrics(y,prediction)
            metrics_rows.append(dict(target=target,model=name,train_n=len(train),test_n=len(test),units=units,**score))
            for mid,smi,observed,pred,raw in zip(test.molecule_id,test.smiles,y,prediction,base_test):
                pred_rows.append(dict(target=target,model=name,molecule_id=mid,smiles=smi,
                                      orca=float(observed),prediction=float(pred),xtb=float(raw),
                                      signed_error=float(pred-observed)))
            print(f'  {name:19s} MAE={score["mae"]:.4f} {units}, bias={score["bias"]:+.4f}',flush=True)
            if name in ['raw_xtb','hybrid_rf','delta_rf','smiles_rf']:
                plot_parity(y,prediction,f'{target}: {name}',args.out/f'parity_{target}_{name}.png',units)
        # Bias distribution on frozen test.
        fig,ax=plt.subplots(figsize=(6,4))
        ax.hist(y-base_test,bins=12)
        ax.axvline(0,ls='--',color='gray')
        ax.set(xlabel=f'ORCA - xTB ({units})',ylabel='Molecules',title=f'{target}: reference correction on frozen holdout')
        fig.tight_layout();fig.savefig(args.out/f'delta_hist_{target}.png',dpi=220);plt.close(fig)
    result=pd.DataFrame(metrics_rows)
    if result.empty: raise ValueError('No target had enough complete paired records')
    result.to_csv(args.out/'model_metrics.csv',index=False)
    pd.DataFrame(pred_rows).to_csv(args.out/'holdout_predictions.csv',index=False)
    pd.DataFrame(qc).to_csv(args.out/'property_audit.csv',index=False)
    for target,grp in result.groupby('target'):
        grp=grp.sort_values('mae')
        fig,ax=plt.subplots(figsize=(8,4.7))
        ax.barh(grp.model,grp.mae)
        ax.invert_yaxis();ax.set_xlabel(f'MAE ({grp.units.iloc[0]})')
        ax.set_title(f'{target}: ORCA prediction on frozen holdout (n={grp.test_n.iloc[0]})')
        for k,val in enumerate(grp.mae): ax.text(val,k,f' {val:.3f}',va='center',fontsize=8)
        fig.tight_layout();fig.savefig(args.out/f'model_comparison_{target}.png',dpi=220);plt.close(fig)
    (args.out/'run_metadata.json').write_text(json.dumps({'input':str(args.data),'test_ids':ids,
      'geometry':'ORCA single-point on xTB optimized geometry (from prior dataset)',
      'functional':'PBE0/def2-SVP as in prior QC workflow',
      'split':'original frozen 19; any molecule with identical canonical isomeric SMILES excluded from train',
      'feature_order':DESC,'fingerprint':'Morgan radius 2, 1024 bits, no chirality flag'},indent=2))
    print('\nResults:',args.out,flush=True)
    print('\nSorted holdout results:\n', result.sort_values(['target','mae'])[['target','model','test_n','mae','rmse','bias','r2']].to_string(index=False))

if __name__=='__main__': main()
