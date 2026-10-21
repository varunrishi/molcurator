#!/usr/bin/env python3
"""MolCurator final figures from real cluster result CSVs. No model retraining."""
from pathlib import Path
import argparse, json, shutil, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({'font.size':11, 'axes.spines.top':False, 'axes.spines.right':False,
                     'savefig.bbox':'tight', 'figure.dpi':120})
MODELS=['mean','morgan_rf','xtb_rf','combined_rf','xtb_ridge']
NAMES={'mean':'Mean','morgan_rf':'Morgan RF','xtb_rf':'xTB RF','combined_rf':'Combined RF','xtb_ridge':'xTB Ridge'}

def save(fig, path):
    fig.savefig(path,dpi=260,facecolor='white'); plt.close(fig)
    print('  +', path.name, flush=True)

def load_csv(path, required=()):
    if not path.exists():
        print('  SKIP missing:', path); return None
    try:
        df=pd.read_csv(path)
        missing=set(required)-set(df.columns)
        if missing:
            print('  SKIP missing columns:',path.name,missing);return None
        return df
    except Exception as e:
        print('  SKIP unreadable:',path,e);return None

def bar_compare(df, label, out):
    if df is None:return
    tmp=df.copy();tmp['model']=tmp.model.astype(str)
    tmp=tmp[tmp.model.isin(MODELS)]
    if not len(tmp):return
    piv=tmp.pivot_table(index='model',columns='dataset',values='mae_ev',aggfunc='first').reindex(MODELS)
    fig,ax=plt.subplots(figsize=(9.5,5.1))
    x=np.arange(len(piv));cats=list(piv.columns);w=.75/max(1,len(cats))
    for i,col in enumerate(cats):
        vals=piv[col].to_numpy(float)
        bars=ax.bar(x+(i-(len(cats)-1)/2)*w,vals,w,label=col)
        for b,v in zip(bars, vals):
            if np.isfinite(v):ax.annotate(f'{v:.3f}',(b.get_x()+b.get_width()/2,v),ha='center',va='bottom',fontsize=8,xytext=(0,2),textcoords='offset points')
    ax.set_xticks(x,[NAMES.get(a,a) for a in piv.index],rotation=17)
    ax.set_ylabel('S1 MAE (eV) — lower is better');ax.set_title(label);ax.legend(frameon=False)
    ax.set_ylim(0,max(0.8,np.nanmax(piv.values)*1.18))
    save(fig,out)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default='/work/AG_Presselt/MolCurator')
    p.add_argument('--output',default=None)
    args=p.parse_args();root=Path(args.root)
    out=Path(args.output) if args.output else root/'presentation_figures_final'
    out.mkdir(parents=True,exist_ok=True)
    print('Source:',root,'Output:',out,flush=True)
    index=[]
    # Two complementary workflow figures: completed benchmark vs proposed design loop.
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    def flowchart(filename, title, boxes, footer):
        fig,ax=plt.subplots(figsize=(12,2.9));ax.set_xlim(0,12);ax.set_ylim(0,3);ax.axis('off')
        ax.text(.35,2.67,title,size=16,weight='bold',ha='left')
        n=len(boxes);usable=11.25;gap=.23;width=(usable-gap*(n-1))/n
        for j,(head,sub) in enumerate(boxes):
            x=.35+j*(width+gap)
            patch=FancyBboxPatch((x,1.02),width,1.1,boxstyle='round,pad=0.02,rounding_size=.14',facecolor='#e8f2f5',edgecolor='#6c8d9a',lw=1)
            ax.add_patch(patch);ax.text(x+width/2,1.73,head,ha='center',va='center',weight='bold',fontsize=10)
            ax.text(x+width/2,1.32,sub,ha='center',va='center',fontsize=8)
            if j+1<n:
                ax.annotate('',xy=(x+width+gap-.035,1.56),xytext=(x+width+.02,1.56),arrowprops={'arrowstyle':'->','lw':1.4})
        ax.text(.36,.50,footer,fontsize=9,color='#4c5662')
        save(fig,out/filename)
    flowchart('00a_completed_workflow.png','What the benchmark implements',[
        ('QM9','existing SMILES'),('RDKit','3D + MMFF94'),('xTB','optimize, features'),('ORCA','S1 + f labels'),('ML','fit + validate')],
        'Measured: 276 QC labels; 94 conformer-aware workflows; 48 additional QM9 tests')
    flowchart('00b_goal_directed_loop_proposed.png','Goal-directed MolCurator: the next integration step',[
        ('Input','seed + targets'),('Generate','valid variants'),('Fast filter','novelty + xTB'),('Rank','ML + constraints'),('Verify','ORCA + conformers'),('Update','add labels; repeat')],
        'Proposed loop: a good surrogate is one component, not itself a generative agent')
    # QC dataset overview
    qc=load_csv(root/'ml276/ml_dataset.csv',('molecule_id','s1_ev'))
    if qc is not None:
        vals=pd.to_numeric(qc.s1_ev,errors='coerce').dropna()
        fig,ax=plt.subplots(figsize=(7.2,4.6));ax.hist(vals,bins=24,edgecolor='white')
        ax.set(xlabel='ORCA vertical S1 excitation energy (eV)',ylabel='Molecules',title=f'Curated QM9 QC labels (n={len(vals)})')
        ax.axvline(vals.median(),ls='--',c='k',lw=1,label=f'Median {vals.median():.2f} eV');ax.legend(frameon=False)
        save(fig,out/'01_s1_distribution_276.png')
        if {'xtb_gap_ev','xtb_dipole_debye'}.issubset(qc.columns):
            tmp=qc[['xtb_gap_ev','s1_ev']].apply(pd.to_numeric,errors='coerce').dropna()
            fig,ax=plt.subplots(figsize=(6.5,5));ax.scatter(tmp.xtb_gap_ev,tmp.s1_ev,alpha=.6,s=27)
            ax.set(xlabel='xTB HOMO–LUMO gap (eV)',ylabel='ORCA vertical S1 (eV)',title='Low-cost descriptor vs high-level label')
            if len(tmp)>2:
                r=tmp.corr().iloc[0,1];ax.text(.02,.98,f'Pearson r = {r:.2f}',transform=ax.transAxes,va='top')
            save(fig,out/'02_xtb_gap_vs_orca_s1_276.png')
    # Workflow funnel actual summary JSONs
    summaries=[]
    for path in sorted((root/'qm9_100/conformer_runs').glob('*/summary.json')):
        try:summaries.append(json.loads(path.read_text()))
        except Exception as e:print('  SKIP summary:',path,e)
    if summaries:
        sums=pd.DataFrame(summaries)
        stages=[('ETKDG generated','n_embedded'),('FF clusters','n_ff_clusters'),('xTB successes','n_xtb_success'),('xTB clusters','n_xtb_clusters'),('ORCA selected','n_orca_selected'),('ORCA successes','n_orca_success')]
        stages=[(label,int(pd.to_numeric(sums[col],errors='coerce').fillna(0).sum())) for label,col in stages if col in sums.columns]
        fig,ax=plt.subplots(figsize=(9.5,4.7));x=np.arange(len(stages));vals=[v for _,v in stages]
        bars=ax.bar(x,vals,color=['#5783b7']+['#419d8a']*(len(stages)-1))
        ax.set_xticks(x,[k for k,_ in stages],rotation=18,ha='right');ax.set_ylabel('Total geometries / calculations')
        ax.set_title(f'Conformer-selection funnel ({len(sums)} molecules)')
        for b,v in zip(bars,vals):ax.text(b.get_x()+b.get_width()/2,b.get_height()+max(vals)*.01,f'{v:,}',ha='center',fontsize=10)
        ax.set_ylim(0,max(vals)*1.13);save(fig,out/'03_conformer_selection_funnel.png')
        for key,label,filename in [('n_ff_clusters','Force-field clusters','04_ff_cluster_counts.png'),('n_xtb_clusters','xTB clusters','05_xtb_cluster_counts.png')]:
            if key in sums:
                v=pd.to_numeric(sums[key],errors='coerce').dropna().astype(int)
                counts=v.value_counts().sort_index()
                fig,ax=plt.subplots(figsize=(6.8,4.6));ax.bar(counts.index.astype(str),counts.values)
                ax.set(xlabel=f'{label} per molecule',ylabel='Molecules',title=f'Distribution of {label.lower()} (n={len(v)})')
                save(fig,out/filename)
        if {'n_ff_clusters','n_xtb_clusters'}.issubset(sums.columns):
            xy=sums[['n_ff_clusters','n_xtb_clusters']].apply(pd.to_numeric,errors='coerce').dropna()
            points=xy.value_counts().reset_index(name='molecules')
            fig,ax=plt.subplots(figsize=(6.5,5.1));sp=ax.scatter(points.n_ff_clusters,points.n_xtb_clusters,s=35+points.molecules*16,alpha=.7)
            ax.set(xlabel='FF clusters / molecule',ylabel='xTB clusters / molecule',title='Diversity retained after xTB optimization')
            save(fig,out/'06_ff_vs_xtb_clusters.png')
    # Conformer sensitivity
    comp=load_csv(root/'qm9_100/conformer_evaluation/conformer_comparison.csv',('molecule_id','s1_range_ev','abs_shift_lowest_ev'))
    if comp is not None:
        sh=pd.to_numeric(comp.abs_shift_lowest_ev,errors='coerce').dropna()
        fig,ax=plt.subplots(figsize=(7.2,4.6));ax.hist(sh,bins=np.linspace(0,max(.55,sh.max()*1.05),26),edgecolor='white')
        ax.set(xlabel='Absolute difference: original vs selected-lowest S1 (eV)',ylabel='Molecules',title=f'Geometry-protocol label shifts (n={len(sh)})')
        save(fig,out/'07_protocol_label_shift_distribution.png')
        thresholds=np.array([.05,.1,.2,.4]);counts=[int((sh>v).sum()) for v in thresholds]
        fig,ax=plt.subplots(figsize=(7,4.4));bars=ax.bar([f'> {v:.2f} eV' for v in thresholds],counts)
        ax.set(ylabel=f'Molecules out of {len(sh)}',title='Frequency of substantial S1 label shifts');ax.set_ylim(0,max(counts+[1])*1.2)
        for b,v in zip(bars,counts):ax.text(b.get_x()+b.get_width()/2,v+.15,str(v),ha='center')
        save(fig,out/'08_label_shift_thresholds.png')
        ranges=comp.copy();ranges['s1_range_ev']=pd.to_numeric(ranges.s1_range_ev,errors='coerce')
        if 'n_valid_conformers' in ranges.columns:ranges=ranges[pd.to_numeric(ranges.n_valid_conformers,errors='coerce')>=2]
        top=ranges.nlargest(12,'s1_range_ev').sort_values('s1_range_ev')
        fig,ax=plt.subplots(figsize=(8.3,5.6));ax.barh(top.molecule_id,top.s1_range_ev)
        ax.set(xlabel='S1 range among ORCA-calculated conformers (eV)',title='Most conformation-sensitive molecules')
        save(fig,out/'09_top_within_molecule_s1_ranges.png')
        for field,xlabel,fname in [('xtb_dipole_debye_range','Dipole range across conformers (D)','10_dipole_vs_s1_range.png'),('s1_oscillator_strength_range','Oscillator-strength range','11_f_vs_s1_range.png')]:
            if field in ranges.columns:
                tmp=ranges[[field,'s1_range_ev']].apply(pd.to_numeric,errors='coerce').dropna()
                fig,ax=plt.subplots(figsize=(6.4,5));ax.scatter(tmp[field],tmp.s1_range_ev,alpha=.7,s=45)
                ax.set(xlabel=xlabel,ylabel='S1 range (eV)',title='Property-dependent conformational sensitivity')
                save(fig,out/fname)
    # ML metrics across three evaluations
    original=load_csv(root/'ml276/model_comparison_94_vs_276.csv',('model','dataset','mae_ev'))
    external=load_csv(root/'external_test50/external_metrics.csv',('model','mae_ev'))
    if original is not None:
        # Fixed holdout only — fair training-set-size comparison
        bar_compare(original,'Same 19 held-out molecules: 75 vs 257 training labels',out/'12_ml_holdout_94_vs_276.png')
    if external is not None:
        tmp=external.set_index('model').reindex(MODELS)
        fig,ax=plt.subplots(figsize=(8.5,4.8));bars=ax.bar([NAMES[m] for m in tmp.index],tmp.mae_ev)
        ax.set(ylabel='MAE on external QM9 molecules (eV)',title=f'Independent QM9 test (n={int(tmp.test_n.dropna().iloc[0]) if "test_n" in tmp else "?"})')
        ax.tick_params(axis='x',rotation=17);ax.set_ylim(0,max(tmp.mae_ev)*1.18)
        for b,v in zip(bars,tmp.mae_ev):
            if pd.notna(v):ax.annotate(f'{v:.3f}',(b.get_x()+b.get_width()/2,v),ha='center',va='bottom',xytext=(0,3),textcoords='offset points',fontsize=9)
        save(fig,out/'13_external_ml_mae.png')
    if original is not None and external is not None:
        expanded=original[original.dataset.eq('expanded')][['model','mae_ev']].assign(dataset='Frozen holdout (n=19)')
        other=external[['model','mae_ev']].assign(dataset='New QM9 (n=48)')
        bar_compare(pd.concat([expanded,other]),'Trained on 257: performance on two distinct test sets',out/'14_frozen_vs_external_mae.png')
    # Prediction parity on external, with residual plot
    preds=load_csv(root/'external_test50/external_predictions.csv',('s1_ev','combined_rf_pred_ev'))
    if preds is not None:
        tmp=preds[['s1_ev','combined_rf_pred_ev']].apply(pd.to_numeric,errors='coerce').dropna()
        y=tmp.s1_ev.to_numpy();yh=tmp.combined_rf_pred_ev.to_numpy();lims=(min(y.min(),yh.min())-.2,max(y.max(),yh.max())+.2)
        fig,ax=plt.subplots(figsize=(6.6,5.5));ax.scatter(y,yh,s=40,alpha=.75)
        ax.plot(lims,lims,'--',color='gray');ax.set(xlim=lims,ylim=lims,xlabel='ORCA S1 (eV)',ylabel='Predicted S1 (eV)',title=f'External combined RF parity (n={len(tmp)})')
        ax.set_aspect('equal',adjustable='box');save(fig,out/'15_external_combined_parity.png')
        fig,ax=plt.subplots(figsize=(7,4.5));ax.scatter(y,yh-y,s=40,alpha=.75)
        ax.axhline(0,ls='--',color='gray');ax.set(xlabel='ORCA S1 (eV)',ylabel='Prediction - ORCA (eV)',title='External combined RF residuals')
        save(fig,out/'16_external_residuals.png')
    # existing learning curve (do not reinvent)
    lc=root/'ml276/learning_curve.png'
    if lc.exists():
        shutil.copy2(lc,out/'17_learning_curve.png');print('  + 17_learning_curve.png (copied)')
    # Render an informative index / QC summary
    files=sorted(x.name for x in out.glob('*.png'))
    notes=['MolCurator plots generated directly from cluster results.','', 'Source data: '+str(root),
           'Conformer funnel is a reduction in count, not computational speedup.',
           'Zero S1 range for molecules with one calculated conformer is not evidence of rigidity.',
           'Geometry-protocol label shifts are not equivalent to within-molecule conformer S1 ranges.',
           'ML is a surrogate predictor of ORCA vertical S1, not experimentally measured fluorescence.',
           'External QM9 molecules are out-of-sample within QM9, not out-of-domain dyes.',
           'A model scoring molecules is not yet a goal-conditioned generation agent.', '', 'Files:'] + ['- '+f for f in files]
    (out/'FIGURE_INDEX.txt').write_text('\n'.join(notes)+'\n')
    print(f'Finished: {len(files)} figures, {out}',flush=True)

if __name__=='__main__':main()
