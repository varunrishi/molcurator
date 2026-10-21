#!/usr/bin/env python3
"""Generate reproducible figures and a Markdown report from MolCurator CSV outputs."""
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TARGET=(3.0,3.5)
COLORS={'Raw xTB':'#8b93a7','Constant offset':'#3f7797','Linear':'#bb715b'}

def save(fig, out, name):
    fig.tight_layout()
    fig.savefig(out / (name+'.png'),dpi=220,bbox_inches='tight')
    fig.savefig(out / (name+'.pdf'),bbox_inches='tight')
    plt.close(fig)

def numerical(df,key):
    return pd.to_numeric(df[key],errors='coerce')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('/work/AG_Presselt/MolCurator'))
    p.add_argument('--out',type=Path,default=Path('research/property_validation_results/report'))
    args=p.parse_args(); out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    root=args.root
    calibration_metrics=root/'calibration24/results/metrics.json'
    validation=root/'target_validation/screen/validation_results.csv'
    rankings=root/'calibrated_ranking.csv'
    if not validation.exists(): raise SystemExit(f'Missing {validation}')
    if not rankings.exists(): raise SystemExit(f'Missing {rankings}')
    v=pd.read_csv(validation); r=pd.read_csv(rankings)
    for col in ['candidate_id','xtb_gap_ev','orca_gap_ev','selection_probability','status']:
        if col not in v: raise SystemExit(f'Missing {col} in {validation}')
    if not {'candidate_id','calibrated_gap_ev','selected','raw_xtb_gap_ev'}.issubset(r.columns):
        raise SystemExit('Ranking CSV has missing required columns')
    v=v.merge(r[['candidate_id','calibrated_gap_ev','selected']],on='candidate_id',how='left',validate='one_to_one')
    v=v[(v.status=='ok') & v.orca_gap_ev.notna()].copy()
    v['raw']=numerical(v,'xtb_gap_ev')
    v['constant']=v['raw']+2.2617441034023127
    v['linear']=v['raw']*0.8270780546046135+2.9901896256531098
    v['dft']=numerical(v,'orca_gap_ev')
    v['weight']=1.0/numerical(v,'selection_probability')
    v=v.replace([np.inf,-np.inf],np.nan).dropna(subset=['raw','constant','linear','dft','weight'])
    if len(v)==0: raise SystemExit('No complete successful validation records')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','savefig.facecolor':'white'})
    # Fig 1: prediction parity, three panels
    fig,axs=plt.subplots(1,3,figsize=(12.5,4.1),sharex=True,sharey=True)
    lo=min(v[['raw','constant','linear','dft']].min())-.3;hi=max(v[['raw','constant','linear','dft']].max())+.3
    for ax,(title,key) in zip(axs,[('Raw GFN2-xTB','raw'),('Constant offset','constant'),('Linear calibration','linear')]):
        ax.scatter(v['dft'],v[key],s=30,alpha=.75,edgecolors='white',linewidths=.3)
        ax.plot([lo,hi],[lo,hi],ls='--',color='0.35',lw=1)
        mae=np.mean(np.abs(v[key]-v['dft']))
        ax.set(title=f'{title}\nMAE = {mae:.3f} eV',xlabel='ORCA B3LYP gap (eV)',xlim=(lo,hi),ylim=(lo,hi))
    axs[0].set_ylabel('Predicted gap (eV)')
    save(fig,out,'01_parity')
    # Fig 2: MAE
    labels=['Raw xTB','Constant offset','Linear'];cols=['raw','constant','linear']
    sample=[float(np.mean(abs(v[c]-v.dft))) for c in cols]
    weighted=[float(np.average(abs(v[c]-v.dft),weights=v.weight)) for c in cols]
    fig,ax=plt.subplots(figsize=(7.7,4.5));x=np.arange(3);w=.34
    bars=ax.bar(x-w/2,sample,w,label='Validation sample',color='#7594b4')
    bars2=ax.bar(x+w/2,weighted,w,label='Inverse-probability weighted',color='#ca916a')
    for b in [*bars,*bars2]: ax.annotate(f'{b.get_height():.3f}',(b.get_x()+b.get_width()/2,b.get_height()),ha='center',va='bottom',fontsize=9,xytext=(0,3),textcoords='offset points')
    ax.set_xticks(x,labels);ax.set_ylabel('MAE (eV)');ax.set_ylim(0,max(sample+weighted)*1.18);ax.legend(frameon=False)
    save(fig,out,'02_mae_comparison')
    # Fig 3: residuals against DFT, with true target window
    fig,ax=plt.subplots(figsize=(8.2,4.6))
    for lab,col in zip(labels,cols):
        ax.scatter(v.dft,v[col]-v.dft,label=lab,s=28,alpha=.72)
    ax.axhline(0,color='0.35',ls='--');ax.axvspan(*TARGET,color='gray',alpha=.12,label='Target window')
    ax.set(xlabel='ORCA B3LYP gap (eV)',ylabel='Predicted − ORCA gap (eV)',title='Residuals across chemical space')
    ax.legend(frameon=False,ncol=2)
    save(fig,out,'03_residuals')
    # Fig 4: target window and near-target distribution
    fig,ax=plt.subplots(figsize=(8,4.4))
    ax.hist(v.dft,bins=18,color='#648aa5',alpha=.85,edgecolor='white')
    ax.axvspan(*TARGET,color='#ca916a',alpha=.25,label='3.0–3.5 eV target')
    ax.set(xlabel='ORCA B3LYP gap (eV)',ylabel='Validated molecule count',title='Target scarcity in 60-molecule validation sample')
    ax.legend(frameon=False)
    save(fig,out,'04_dft_gap_distribution')
    # Fig 5: screening fraction and observed hit retrieval across margins
    margins=np.array([.2,.5,.75,1.,1.5]); fig,ax=plt.subplots(figsize=(8,4.6))
    def dist(y): return np.maximum.reduce([TARGET[0]-y,y-TARGET[1],np.zeros(len(y))])
    for name,col in zip(labels,cols):
        shares=[float((dist(v[col])<=m).mean()) for m in margins]
        ax.plot(margins,shares,marker='o',label=name)
    ax.set(xlabel='Screening margin around 3.0–3.5 eV (eV)',ylabel='Fraction of validated sample screened in',ylim=(0,1.05),title='Selection workload vs screening margin')
    ax.legend(frameon=False)
    save(fig,out,'05_screening_workload')
    # Fig 6: top 20 ranked; highlight reused QC candidates
    top=r[r.status=='ok'].head(20).copy()
    if len(top):
        fig,ax=plt.subplots(figsize=(10,5.7));top=top.iloc[::-1]
        ax.barh(top.candidate_id.astype(str),numerical(top,'calibrated_gap_ev'),color=['#b8a6a3' if id in set(v.candidate_id) else '#5b849d' for id in top.candidate_id])
        ax.axvspan(*TARGET,color='#cfb48d',alpha=.23)
        ax.axvline(3.5+.75,color='0.35',ls=':',label='Upper + 0.75 eV')
        ax.set(xlabel='Linearly calibrated gap (eV)',title='Top-ranked screened molecules (muted: already validated)')
        ax.legend(frameon=False);save(fig,out,'06_top20_ranking')
    hits=v[v.dft.between(*TARGET)]
    stats={'n_validation_success':int(len(v)),'n_target_hits_observed':int(len(hits)),
           'sample_mae_ev':dict(zip(labels,sample)),'pool_weighted_mae_ev':dict(zip(labels,weighted)),
           'target_window_ev':list(TARGET), 'note':'Weighted errors are estimates for the 568 successfully screened population under the recorded stratified design.'}
    (out/'statistics.json').write_text(json.dumps(stats,indent=2))
    hit_table='\n'.join(f'| {row.candidate_id} | {row.dft:.4f} | {row.raw:.4f} | {row.linear:.4f} |' for row in hits.itertuples()) or '| No observed hits | — | — | — |'
    report=f'''# MolCurator — HOMO–LUMO Gap Calibration and Validation\n\n**Method:** GFN2-xTB optimized geometry, ORCA B3LYP/def2-SVP single-point HOMO–LUMO orbital gap.\n\n## Research summary\n\nOur property-validation adapters completed 24/24 initial calibration calculations and 60/60 target-enriched ORCA validations. The screening pool had 568 successful xTB calculations out of 600 selected candidate molecules. The fixed 24-molecule calibration experiment trained a constant-offset and linear gap correction; this subsequent 60-molecule evaluation was selected using strata defined by distance to the calibrated target.\n\n## Calibration models\n\n- Constant offset: $E_{{DFT}}^{{pred}}=E_{{xTB}}+2.261744$ eV.\n- Linear: $E_{{DFT}}^{{pred}}=0.827078 E_{{xTB}}+2.990190$ eV.\n- Target: **3.0–3.5 eV**, with a provisional **±0.75 eV** ranking margin.\n\n## Validation metrics\n\n| Method | Sample MAE (eV) | Inverse-probability-weighted MAE (eV) |\n|---|---:|---:|\n| Raw GFN2-xTB | {sample[0]:.3f} | {weighted[0]:.3f} |\n| Constant offset | {sample[1]:.3f} | {weighted[1]:.3f} |\n| Linear calibration | {sample[2]:.3f} | {weighted[2]:.3f} |\n\n![MAE](02_mae_comparison.png)\n\n![Parity](01_parity.png)\n\n![Residuals](03_residuals.png)\n\n## Screening and target hits\n\nThe validation sample contains **{len(hits)}** confirmed hit(s) in the 3.0–3.5 eV target window. The top-ranked screened structures were largely already covered by the target-enriched validation cohort. The frozen sample probabilities support design-weighted estimates of prediction error, **not a guarantee of screening recall**. With just {len(hits)} observed hit(s), empirical hit recall is highly uncertain.\n\n| Candidate ID | ORCA gap (eV) | xTB gap (eV) | Linearly calibrated gap (eV) |\n|---|---:|---:|---:|\n{hit_table}\n\n![Target distribution](04_dft_gap_distribution.png)\n\n![Margin tradeoff](05_screening_workload.png)\n\n![Ranking](06_top20_ranking.png)\n\n## Interpretation and implementation notes\n\nThe calibrated models substantially reduce the systematic offset between xTB and B3LYP orbital gaps. Linear calibration performs best on this validation cohort; these coefficients are **method specific** and should not be applied to PBE0 results, vertical S1 energies or S1–T1 gaps. The shared agent contract remains unchanged: `Prediction.value` is the raw xTB gap, and a separate screening layer applies the calibration for ranking. One xTB-selected FF-minimum geometry is passed to one ORCA attempt per validation candidate.\n\n**Limitations:** the target-enriched validation cohort is not a simple random sample; QM9 chemical space is narrow; just {len(hits)} observed hit(s) cannot establish recall; sampling and model fit uncertainty are not estimated here. A broader, positive-enriched and independently probability-sampled validation campaign is required before any hard rejection policy.\n\n## Reproducibility and provenance\n\nInputs are the saved `validation_results.csv` (60 ORCA labels) and `calibrated_ranking.csv` (screened-pool ranking); the earlier 24-molecule results provide frozen calibration coefficients. Figures and `statistics.json` can be regenerated using `build_report.py`.\n'''
    (out/'REPORT.md').write_text(report)
    print(f'Wrote {len(list(out.glob("*.png")))} PNG and {len(list(out.glob("*.pdf")))} PDF figures, REPORT.md and statistics.json to {out}')

if __name__=='__main__': main()
