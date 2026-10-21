#!/usr/bin/env python3
"""Score saved 276-label models on a never-trained-on external QC batch."""
import argparse
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from rdkit import Chem,DataStructs
from rdkit.Chem import rdFingerprintGenerator
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score

FEATURES=['xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye']
def canonical(s):
    mol=Chem.MolFromSmiles(str(s))
    return Chem.MolToSmiles(mol,isomericSmiles=True) if mol else None

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('/work/AG_Presselt/MolCurator/external_test50'))
    p.add_argument('--models',type=Path,default=Path('/work/AG_Presselt/MolCurator/ml276'))
    a=p.parse_args()
    files=sorted(a.root.glob('test_*/properties.csv'))
    if not files:raise SystemExit('No completed external properties.csv files yet')
    data=pd.concat([pd.read_csv(f) for f in files],ignore_index=True)
    seen=pd.read_csv(a.models/'ml_dataset.csv')
    known=set(seen.smiles.map(canonical))
    data['canonical_smiles']=data.smiles.map(canonical)
    overlap=data[data.canonical_smiles.isin(known)]
    if len(overlap):raise SystemExit('DATA LEAKAGE: external molecules overlap with training/holdout:\n'+str(overlap.molecule_id.tolist()))
    if data.canonical_smiles.duplicated().any():raise SystemExit('Duplicate external structures found')
    for col in ['s1_ev','s1_oscillator_strength']+FEATURES:data[col]=pd.to_numeric(data[col],errors='coerce')
    ok1=data.xtb_success.astype(str).str.lower().isin(['true','1'])
    ok2=data.orca_success.astype(str).str.lower().isin(['true','1'])
    ok=(ok1&ok2&data.s1_ev.between(.01,20)&data.canonical_smiles.notna()&data.s1_oscillator_strength.ge(0)&data[FEATURES].notna().any(axis=1))
    invalid=data[~ok]
    invalid.to_csv(a.root/'invalid_labels.csv',index=False)
    good=data[ok].copy()
    if len(good)<5:raise SystemExit(f'Only {len(good)} valid labels; wait for more external ORCA results')
    generator=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=1024)
    fps=[]
    for smiles in good.canonical_smiles:
        fp=generator.GetFingerprint(Chem.MolFromSmiles(smiles))
        arr=np.zeros(1024,dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fp,arr)
        fps.append(arr)
    fp=np.stack(fps)
    xtb=good[FEATURES].to_numpy(float)
    xs={'morgan_rf':fp,'xtb_rf':xtb,'combined_rf':np.column_stack([fp,xtb]),'xtb_ridge':xtb}
    y=good.s1_ev.to_numpy(float)
    preds=good[['molecule_id','smiles','s1_ev']].copy()
    metrics=[]
    for name,x in xs.items():
        model_file=a.models/f'{name}.joblib'
        model=joblib.load(model_file)
        pred=model.predict(x)
        preds[name+'_pred_ev']=pred
        metrics.append({'model':name,'test_n':len(y),'mae_ev':mean_absolute_error(y,pred),'rmse_ev':np.sqrt(mean_squared_error(y,pred)),'r2':r2_score(y,pred)})
    # Training set mean baseline must be reconstructed from the exact training partition.
    train=pd.read_csv(a.models/'ml_dataset.csv')
    frozen=pd.read_csv('/work/AG_Presselt/MolCurator/qm9_100/baseline94/frozen_test_ids.csv')
    train=train[~train.molecule_id.isin(frozen.molecule_id)]
    avg=float(train.s1_ev.mean())
    baseline=np.full(len(y),avg)
    preds['mean_pred_ev']=baseline
    metrics.insert(0,{'model':'mean','test_n':len(y),'mae_ev':mean_absolute_error(y,baseline),'rmse_ev':np.sqrt(mean_squared_error(y,baseline)),'r2':r2_score(y,baseline)})
    stats=pd.DataFrame(metrics)
    stats.to_csv(a.root/'external_metrics.csv',index=False)
    preds.to_csv(a.root/'external_predictions.csv',index=False)
    print(f'External evaluation: {len(y)} valid / {len(files)} parsed molecules')
    print(stats.to_string(index=False,float_format=lambda v:f'{v:.4f}'))
    fig,ax=plt.subplots(figsize=(8,5))
    ax.bar(stats.model,stats.mae_ev)
    ax.set_ylabel('MAE on external test (eV)');ax.set_title(f'External QM9 test, n={len(y)}')
    ax.tick_params(axis='x',rotation=25)
    fig.tight_layout();fig.savefig(a.root/'external_model_mae.png',dpi=220);plt.close(fig)
    fig,ax=plt.subplots(figsize=(6,6))
    ax.scatter(y,preds.combined_rf_pred_ev)
    lo=min(y.min(),preds.combined_rf_pred_ev.min());hi=max(y.max(),preds.combined_rf_pred_ev.max())
    ax.plot([lo,hi],[lo,hi],'--',color='gray')
    ax.set(xlabel='ORCA S1 (eV)',ylabel='Predicted S1 (eV)',title=f'External combined RF, n={len(y)}')
    fig.tight_layout();fig.savefig(a.root/'external_combined_parity.png',dpi=220);plt.close(fig)
    print('Saved:',a.root)
if __name__=='__main__':main()
