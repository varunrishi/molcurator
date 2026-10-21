#!/usr/bin/env python3
"""MolCurator multifidelity reporting and untouched external validation.
Requires numpy pandas matplotlib scikit-learn joblib rdkit.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

TARGETS = {
    'homo_ev': ('xtb_homo_ev','orca_homo_ev','eV'),
    'lumo_ev': ('xtb_lumo_ev','orca_lumo_ev','eV'),
    'gap_ev': ('xtb_gap_ev','orca_gap_ev','eV'),
    'dipole_debye': ('xtb_dipole_debye','orca_dipole_debye','D'),
}
DESC = ['xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye']
MODELS = ['raw_xtb','constant_delta','linear_calibration','smiles_rf','xtb_rf','hybrid_rf','delta_rf']


def metrics(y, p):
    return dict(n=len(y), mae=mean_absolute_error(y,p),
                rmse=np.sqrt(mean_squared_error(y,p)), bias=float(np.mean(p-y)),
                r2=r2_score(y,p) if len(y)>1 else np.nan)


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches='tight')
    fig.savefig(path.with_suffix('.pdf'), bbox_inches='tight')
    plt.close(fig)


def report(preds, out, label):
    out.mkdir(parents=True, exist_ok=True)
    metrics_rows=[]
    for target,(cheap,reference,unit) in TARGETS.items():
        d=preds[preds.target==target].copy()
        if d.empty: continue
        if 'prediction' not in d: raise ValueError('Missing prediction column')
        d[['orca','prediction','xtb']]=d[['orca','prediction','xtb']].apply(pd.to_numeric,errors='coerce')
        d=d.dropna(subset=['orca','prediction','xtb'])
        for model,g in d.groupby('model'):
            scores=metrics(g.orca.to_numpy(),g.prediction.to_numpy())
            metrics_rows.append(dict(target=target,model=model,unit=unit,**scores))
        raw=d[d.model=='raw_xtb']
        if not raw.empty:
            fig,ax=plt.subplots(figsize=(6.7,5.5))
            ax.scatter(raw.xtb,raw.orca,alpha=.8,s=38)
            ax.set(xlabel=f'xTB {target} ({unit})',ylabel=f'ORCA {target} ({unit})',title=f'{target}: raw xTB versus ORCA · {label}')
            save(fig,out/f'01_raw_xtb_vs_orca_{target}.png')
            fig,ax=plt.subplots(figsize=(6.7,5.0))
            delta=raw.orca-raw.xtb
            ax.hist(delta,bins=min(15,max(5,len(delta)//2)),edgecolor='white')
            ax.axvline(delta.mean(), linestyle='--',label=f'Mean ORCA − xTB = {delta.mean():.3f} {unit}')
            ax.set(xlabel=f'ORCA − xTB ({unit})',ylabel='Molecules',title=f'{target}: systematic method difference · {label}')
            ax.legend()
            save(fig,out/f'02_correction_distribution_{target}.png')
        fig,ax=plt.subplots(figsize=(7.0,5.6))
        subset=d[d.model.isin(['raw_xtb','constant_delta','delta_rf','smiles_rf'])]
        for model,g in subset.groupby('model'):
            ax.scatter(g.orca,g.prediction,label=model,alpha=.65,s=32)
        values=pd.concat([d.orca,d.prediction]); lo,hi=values.min(),values.max()
        ax.plot([lo,hi],[lo,hi],linestyle='--',color='gray',label='identity')
        ax.set(xlabel=f'ORCA reference ({unit})',ylabel=f'Predicted {target} ({unit})',title=f'{target}: parity · {label}')
        ax.legend(fontsize=8)
        save(fig,out/f'03_parity_{target}.png')
        fig,ax=plt.subplots(figsize=(7.2,5.0))
        for model,g in subset.groupby('model'):
            ax.scatter(g.orca,g.prediction-g.orca,label=model,alpha=.7,s=30)
        ax.axhline(0,linestyle='--',color='gray')
        ax.set(xlabel=f'ORCA reference ({unit})',ylabel=f'Prediction − ORCA ({unit})',title=f'{target}: residuals · {label}')
        ax.legend(fontsize=8)
        save(fig,out/f'04_residuals_{target}.png')
    m=pd.DataFrame(metrics_rows)
    if m.empty: raise ValueError('No valid results found')
    m.to_csv(out/'model_metrics_checked.csv',index=False)
    for target,g in m.groupby('target'):
        g=g.sort_values('mae')
        fig,ax=plt.subplots(figsize=(8.6,5.3))
        ax.barh(g.model,g.mae)
        ax.invert_yaxis()
        ax.set(xlabel=f'MAE ({g.unit.iloc[0]})', title=f'{target}: {label} (n={g.n.iloc[0]})')
        for i,val in enumerate(g.mae): ax.text(val,i,f' {val:.3f}',va='center',fontsize=9)
        save(fig,out/f'05_model_mae_{target}.png')
    print('\nRESULTS:', label, '\n',m.sort_values(['target','mae']).to_string(index=False,float_format=lambda v:f'{v:.4f}'))
    print('Figures:',out)
    return m


def validate_external(root, training, frozen, models, benchmark, out):
    import joblib
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    required={'molecule_id','smiles',*DESC,*(k for a,b,c in TARGETS.values() for k in (a,b))}
    files=sorted(root.glob('test_*/properties.csv'))
    if not files: raise SystemExit('No external properties.csv files found')
    x=pd.concat([pd.read_csv(p) for p in files],ignore_index=True)
    missing=required-set(x.columns)
    if missing: raise SystemExit(f'External property file(s) missing columns: {sorted(missing)}')
    train=pd.read_csv(training)
    fids=set(pd.read_csv(frozen)['molecule_id'].astype(str))
    def canon(s):
        mol=Chem.MolFromSmiles(str(s))
        return Chem.MolToSmiles(mol,isomericSmiles=True) if mol else None
    x['canon']=x.smiles.map(canon); train['canon']=train.smiles.map(canon)
    if x.canon.isna().any(): raise SystemExit('Invalid SMILES in external rows')
    if x.canon.duplicated().any(): raise SystemExit('Duplicate canonical external molecules')
    if set(x.canon).intersection(set(train.canon)):
        raise SystemExit('External set overlaps original training/holdout; stop for leakage audit')
    train_test=train[train.molecule_id.astype(str).isin(fids)]
    if len(train_test)!=19: raise SystemExit('Frozen 19 IDs do not match train metadata')
    train=train[~train.molecule_id.astype(str).isin(fids) & ~train.canon.isin(set(train_test.canon))]
    for c in required.intersection(set(x.columns))-{ 'molecule_id','smiles' }:
        x[c]=pd.to_numeric(x[c],errors='coerce')
    if {'xtb_success','orca_success'}.issubset(x.columns):
        for flag in ('xtb_success','orca_success'):
            x=x[x[flag].astype(str).str.lower().isin(['true','1'])]
    x=x.replace([np.inf,-np.inf],np.nan)
    fpgen=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=1024)
    def fp(s):
        a=np.zeros(1024,dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fpgen.GetFingerprint(Chem.MolFromSmiles(s)),a)
        return a
    cache={s:fp(s) for s in x.canon}
    res=[]; excluded=[]
    for target,(cheap,ref,unit) in TARGETS.items():
        complete=DESC+[ref]
        t=x.dropna(subset=complete).copy()
        valid=t[(t[cheap].notna()) & (t['xtb_gap_ev']>0) & (t['orca_gap_ev']>0)]
        excluded.append({'target':target,'parsed':len(files),'eligible':len(valid),'excluded':len(x)-len(valid)})
        if len(valid)<3: print('Skipping',target,'insufficient valid pairs');continue
        paired_train=train.dropna(subset=DESC+[cheap,ref]).copy()
        paired_train=paired_train[(paired_train.xtb_gap_ev>0)&(paired_train.orca_gap_ev>0)]
        correction=(paired_train[ref]-paired_train[cheap]).mean()
        xtb=valid[DESC].to_numpy(float)
        fingerprints=np.stack([cache[s] for s in valid.canon])
        combined=np.column_stack([fingerprints,xtb])
        matrices={'smiles_rf':fingerprints,'xtb_rf':xtb,'hybrid_rf':combined,'delta_rf':combined,'linear_calibration':xtb}
        nfeat={'smiles_rf':1024,'xtb_rf':4,'hybrid_rf':1028,'delta_rf':1028,'linear_calibration':4}
        true=valid[ref].to_numpy(float)
        for name in MODELS:
            if name=='raw_xtb': pred=valid[cheap].to_numpy(float)
            elif name=='constant_delta': pred=valid[cheap].to_numpy(float)+correction
            else:
                f=models/f'{target}_{name}.joblib'
                if not f.exists(): raise FileNotFoundError(f)
                model=joblib.load(f)
                n=getattr(model,'n_features_in_',None)
                if n!=nfeat[name]: raise ValueError(f'{name}: model expects {n}, got {nfeat[name]}')
                pred=model.predict(matrices[name])
                if name=='delta_rf': pred=pred+valid[cheap].to_numpy(float)
            for (mid,smi,raw,y,p) in zip(valid.molecule_id,valid.smiles,valid[cheap],true,pred):
                res.append(dict(target=target,model=name,molecule_id=mid,smiles=smi,
                                xtb=raw,orca=y,prediction=p,signed_error=p-y))
    result=pd.DataFrame(res)
    if result.empty: raise SystemExit('No complete external paired labels; check ORCA parsed columns')
    out.mkdir(parents=True,exist_ok=True)
    result.to_csv(out/'external_property_predictions.csv',index=False)
    pd.DataFrame(excluded).to_csv(out/'external_coverage.csv',index=False)
    report(result,out,'External QM9')
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['plots','external'])
    p.add_argument('--benchmark',type=Path,default=Path('/work/AG_Presselt/MolCurator/multifidelity_benchmark'))
    p.add_argument('--external',type=Path,default=Path('/work/AG_Presselt/MolCurator/external_test50'))
    p.add_argument('--training',type=Path,default=Path('/work/AG_Presselt/MolCurator/ml276/ml_dataset.csv'))
    p.add_argument('--frozen',type=Path,default=Path('/work/AG_Presselt/MolCurator/qm9_100/baseline94/frozen_test_ids.csv'))
    p.add_argument('--out',type=Path,default=Path('/work/AG_Presselt/MolCurator/multifidelity_next'))
    a=p.parse_args()
    if a.mode=='plots':
        raw=pd.read_csv(a.benchmark/'holdout_predictions.csv')
        report(raw,a.out/'original19','Original frozen 19')
    else:
        validate_external(a.external,a.training,a.frozen,a.benchmark,a.benchmark,a.out/'external48')

if __name__=='__main__': main()
