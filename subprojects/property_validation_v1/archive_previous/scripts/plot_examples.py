#!/usr/bin/env python3
"""Render figures from example measured results; no QC dependencies."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser();p.add_argument('--out',default='figures');a=p.parse_args()
base=Path(__file__).resolve().parents[1];out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
v=pd.read_csv(base/'examples/iteration1_validation.csv')
m=pd.read_csv(base/'examples/model_metrics.csv')
fig,ax=plt.subplots(figsize=(8.5,4.8));x=np.arange(len(v));ax.plot(x,v.predicted_s1_ev,'o-',label='RF predicted');ax.plot(x,v.orca_s1_ev,'D-',label='ORCA validated');ax.axhline(4.5,color='black',linestyle='--',label='Target (4.50 eV)');ax.axhspan(4.3,4.7,alpha=.1,color='gray');ax.set_xticks(x,v.molecule_id,rotation=45,ha='right');ax.set_ylabel('Vertical S1 (eV)');ax.set_title('Iteration 1: selected molecules did not meet target');ax.legend();fig.tight_layout();fig.savefig(out/'iteration1_target_vs_orca.png',dpi=220);plt.close(fig)
models=['morgan_rf','xtb_rf','combined_rf','xtb_ridge'];piv=m[m.model.isin(models)].pivot(index='model',columns='dataset',values='mae_ev').reindex(models)
fig,ax=plt.subplots(figsize=(8.5,4.8));x=np.arange(len(models));cols=['original94','expanded','external48'];width=.26
for j,c in enumerate(cols):ax.bar(x+(j-1)*width,piv[c],width,label=c)
ax.set_xticks(x,['Morgan RF','xTB RF','Combined RF','xTB Ridge']);ax.set_ylabel('S1 MAE (eV)');ax.set_title('Fixed holdout and independent QM9 external evaluation');ax.legend();fig.tight_layout();fig.savefig(out/'ml_performance.png',dpi=220);plt.close(fig)
print('Saved',list(map(str,out.glob('*.png'))))
