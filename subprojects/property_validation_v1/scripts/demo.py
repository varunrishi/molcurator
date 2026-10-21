from pathlib import Path
import argparse
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
here=Path(__file__).resolve().parents[1]/'examples'
d=pd.read_csv(here/'iteration1_validation.csv')
cols=set(d.columns)
if {'predicted_s1_ev','orca_s1_ev'}<=cols:
    fig,ax=plt.subplots(figsize=(7,5));v=d[['predicted_s1_ev','orca_s1_ev']].dropna();ax.scatter(v.predicted_s1_ev,v.orca_s1_ev,s=75);lo=min(v.min());hi=max(v.max());ax.plot([lo,hi],[lo,hi],'k--',lw=1);ax.axhline(4.5,ls=':',color='gray');ax.set(xlabel='ML predicted S1 (eV)',ylabel='ORCA S1 (eV)',title='Iteration 1: selected candidates');fig.tight_layout();fig.savefig(a.out/'iteration1_parity.png',dpi=260);plt.close(fig)
print('Generated sample plots in',a.out)
