from pathlib import Path
import sys,json,base64,html,shutil
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1]
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
FIG=BASE/'plots';FIG.mkdir(exist_ok=True)
m=pd.read_csv(BASE/'repeat_metrics.csv');summary=pd.read_csv(BASE/'repeat_summary.csv');intervals=pd.read_csv(BASE/'interval_metrics.csv');routing=pd.read_csv(BASE/'routing_metrics.csv');p=pd.read_csv(BASE/'test_predictions.csv')
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.bbox':'tight'})
colors={'random':'#176c80','scaffold':'#d38b44'}
fig,axs=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
for ax,name,label in zip(axs,['baseline_85pct','calibrated_65pct'],['Original fit size 85%','Proper fit 65% plus calibration 20%']):
    for j,kind in enumerate(['random','scaffold']):
        d=m[(m.kind==kind)&(m.model==name)];ax.scatter(j+np.linspace(-.08,.08,len(d)),d.mae_ev,color=colors[kind],s=38)
        ax.errorbar(j+.17,d.mae_ev.mean(),yerr=d.mae_ev.std(),fmt='s',capsize=5,color='black')
    ax.set(xticks=[0,1],xticklabels=['Random','Scaffold'],ylabel='Held-out MAE / eV',title=label)
fig.savefig(FIG/'01_mae_repeats.png',dpi=180);plt.close(fig)
fig,axs=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
for ax,kind in zip(axs,['random','scaffold']):
    for method,marker in [('absolute','o'),('normalized','s'),('group_max_normalized','^')]:
        d=intervals[(intervals.kind==kind)&(intervals.method==method)]
        stats=d.groupby('nominal_coverage').empirical_molecule_coverage.agg(['mean','std'])
        ax.errorbar(stats.index,stats['mean'],yerr=stats['std'],marker=marker,capsize=4,label=method.replace('_',' '))
    ax.plot([.87,.98],[.87,.98],'--',color='gray');ax.set(xlabel='Nominal coverage',ylabel='Empirical molecule coverage',title=kind.capitalize(),xticks=[.90,.95]);ax.legend(fontsize=8)
fig.savefig(FIG/'02_interval_coverage.png',dpi=180);plt.close(fig)
fig,axs=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
for ax,kind in zip(axs,['random','scaffold']):
    d=intervals[(intervals.kind==kind)&(intervals.nominal_coverage==.9)]
    for method in ['absolute','normalized','group_max_normalized']:
        x=d[d.method==method];ax.scatter(x.mean_width_ev,x.empirical_molecule_coverage,label=method.replace('_',' '),s=40)
    ax.axhline(.9,ls='--',color='gray');ax.set(xlabel='Mean interval width / eV',ylabel='Empirical coverage',title=kind.capitalize());ax.legend(fontsize=8)
fig.savefig(FIG/'03_width_coverage.png',dpi=180);plt.close(fig)
fig,axs=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
for kind,c in colors.items():
    d=routing[routing.kind==kind];axs[0].plot(range(1,6),d.accepted_fraction,'o-',color=c,label=kind)
    if d.accepted_mae_ev.notna().any():axs[1].scatter(d.accepted_mae_ev,d.routed_mae_ev,color=c,label=kind,s=45)
axs[0].set(xlabel='Repeat number',ylabel='Fraction accepted for ML',title='Default conservative routing',ylim=(-.02,.5));axs[0].legend()
axs[1].set(xlabel='Accepted subset MAE / eV',ylabel='Routed subset ML MAE / eV',title='Random-split selective error');axs[1].legend()
fig.savefig(FIG/'04_abstention.png',dpi=180);plt.close(fig)
fig,ax=plt.subplots(figsize=(11,4.5),layout='constrained')
d=p[(p.kind=='random')&(p.seed==20261022)].sort_values('calibrated_prediction_ev').reset_index(drop=True)
xx=np.arange(len(d));ax.fill_between(xx,d.lower90_ev,d.upper90_ev,alpha=.22,color=colors['random'],label='Nominal 90% normalized band')
ax.plot(xx,d.calibrated_prediction_ev,color=colors['random'],lw=1,label='ML estimate')
ax.scatter(xx,d.xtb_gap_ev,c=np.where(d.route=='use_ml',colors['random'],colors['scaffold']),s=16,label='xTB labels; orange routed')
ax.set(xlabel='Held-out molecule ranked by prediction',ylabel='Orbital gap / eV',title='Fixed first-seed deployment model');ax.legend(fontsize=8)
fig.savefig(FIG/'05_example_intervals.png',dpi=180);plt.close(fig)
interval_summary=intervals.groupby(['kind','method','nominal_coverage']).agg(coverage_mean=('empirical_molecule_coverage','mean'),coverage_sd=('empirical_molecule_coverage','std'),width_mean_ev=('mean_width_ev','mean'),complete_group_coverage_mean=('empirical_complete_group_coverage','mean')).reset_index();interval_summary.to_csv(BASE/'interval_summary.csv',index=False)
route_summary=routing.groupby('kind').agg(accepted_fraction_mean=('accepted_fraction','mean'),accepted_fraction_min=('accepted_fraction','min'),accepted_fraction_max=('accepted_fraction','max'),accepted_mae_mean_ev=('accepted_mae_ev','mean'),routed_mae_mean_ev=('routed_mae_ev','mean'),accepted_90_coverage_mean=('accepted_interval90_coverage','mean')).reset_index();route_summary.to_csv(BASE/'routing_summary.csv',index=False)
def img(name,caption):
    data=base64.b64encode((FIG/name).read_bytes()).decode();return f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(caption)}"><figcaption>{caption}</figcaption></figure>'
def table(d):return '<div class="table">'+d.to_html(index=False,border=0,float_format=lambda x:f'{x:.4f}',na_rep='not applicable')+'</div>'
doc='''<!doctype html><html><head><meta charset="utf-8"><title>MolCurator repeated splits uncertainty and abstention</title><style>body{font:16px Segoe UI,Arial,sans-serif;line-height:1.6;max-width:1120px;margin:40px auto;padding:0 24px;color:#1b3039}h1{font-size:32px}h2{margin-top:38px}img{width:100%}figure{margin:24px 0}figcaption{font-size:14px;color:#52636b}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d8e2e6;padding:9px;text-align:left}th{background:#173e4d;color:white}tr:nth-child(even){background:#f1f6f7}pre{background:#f1f6f7;padding:16px;overflow:auto}a{color:#176c80}</style></head><body>
<h1>MolCurator repeated splits uncertainty and abstention</h1><p>22 October 2026. Local extension of the 1000-molecule experiment using its 948 successful xTB labels. No new electronic calculations and no Git publishing.</p>
<p><b>Five repeats give MAE 0.498 ± 0.026 eV for random splits and 0.517 ± 0.062 eV for scaffold splits.</b> These are means and sample standard deviations across seeds, not confidence intervals or independent external experiments. The original 0.407 eV result was a favorable random partition. Hyperparameters were fixed from the earlier study; this is a repeatability analysis of that configuration, not a new unbiased model-family benchmark.</p>
<h2>Experimental design</h2><p>Each seed changes the partition and ExtraTrees random state. The frozen model uses 160 trees, minimum leaf size 1, max_features 0.7, and the same 2048-bit chiral Morgan fingerprints plus 13 descriptors. The primary repeat model fits 85% and tests 15%, matching the earlier final development size. A second model fits approximately 65%, reserves 20% solely for interval calibration and tests on the same 15%. Calibration data are never used to fit that second model. Grouped partitions keep exact Murcko scaffolds disjoint across proper fit, calibration and test; all acyclic molecules form one group. Group-size balancing does not inspect labels.</p>'''
doc+=table(summary)+img('01_mae_repeats.png','Figure 1. Individual repeat MAEs and mean ± sample SD. The calibrated model has less fitting data; its point errors must not be confused with those of the 85% model.')
doc+='''<h2>Calibration and observed coverage</h2><p>For absolute split conformal, calibration scores are |y − prediction|. The order statistic is ceil((n_cal + 1) × nominal coverage), with no interpolated quantile. Normalized scores divide the residual by the fitted ensemble standard deviation, floored at 0.10 eV. The deployed model uses the normalized method selected before testing. A group-max comparator instead takes the largest normalized residual within each calibration scaffold before forming its quantile.</p>
<p><b>The normalized nominal 90% intervals covered only 87.7% of random-test molecules and 89.3% of scaffold-test molecules on average.</b> Absolute nominal 90% intervals reached 91.5% and 87.1% respectively. These methods were not switched or retuned after seeing test outcomes. Calibration is an estimation procedure, not proof that every tested or future subset has the nominal coverage. Coverage after acceptance filtering can differ further.</p>'''
doc+=table(interval_summary)+img('02_interval_coverage.png','Figure 2. Empirical coverage mean ± SD across five seeds. The diagonal marks nominal coverage, not a guarantee under scaffold shift.')+img('03_width_coverage.png','Figure 3. Interval width and empirical coverage for nominal 90% bands. Wider group-max bands generally cover more molecules, but do not certify unseen-scaffold performance.')
doc+='''<p>Exchangeability assumptions matter. Molecule-wise calibration does not establish conditional coverage for unfamiliar scaffolds, nor for a subset selected by an abstention rule. Scaffold groups also vary in size and composition. The group-max comparator is a conservative diagnostic; its formal group-level assumptions are not established by this dataset. The report therefore gives measured molecule and complete-group coverage separately.</p>
<h2>Default abstention policy</h2><p>A valid molecule is routed to physical PREDICT if any rule fires: an unseen scaffold; fingerprint similarity below max(0.25, the fit-only leave-one-out 10th percentile); heavy-atom count outside the fitted range; an element absent from fitting scope; a nominal 90% interval half-width above 1.0 eV; or a negative gap estimate. The 1.0 eV limit is an explicit operational tolerance, not a calibrated error bound. Invalid, radical or net-charged inputs go to input review because the existing physical backend also does not support them.</p>
<p>The strict unseen-scaffold rule means <b>100% of the scaffold holdouts are routed to physical prediction by construction</b>. No accepted-scaffold-subset accuracy is claimed. On random splits the policy accepts 23.8–35.7% of candidates, averaging 32.2%. The accepted subset has mean MAE about 0.313 eV, versus about 0.615 eV for the routed subset. These conditional scores are descriptive and do not prove calibrated selective coverage; accepted normalized 90% coverage averaged about 86.9%.</p>'''
doc+=table(route_summary)+img('04_abstention.png','Figure 4. Default ML acceptance and conditional errors. The grouped holdout has no ML-accepted molecules because its scaffolds are deliberately unseen.')+img('05_example_intervals.png','Figure 5. The first random seed was fixed as the deployment example before testing, rather than selecting the best seed. Orange points are routed to physical prediction.')
doc+='''<h2>Using the local router</h2><p>router.py returns an explicit route and reasons for every original ID. Abstained rows retain a diagnostic ML estimate and interval, but accepted_ml_value_ev is null. They cannot silently be used as accepted ML predictions. No XYZ is created by ML. Physical execution requires an explicit flag and nonnegative molecule budget; ORCA is never called automatically.</p>
<pre>python router.py --model models/random_calibrated_router.joblib \
  --input routing_example.csv --output routes.json

# Opt in to physical PREDICT for at most ten routed molecules
python router.py --model models/random_calibrated_router.joblib \
  --input generated.csv --output hybrid_results.json \
  --run-physical --physical-budget 10 --xyz-dir physical_run/xyz</pre>
<p>Physical execution requires the installed MolCurator package and configured xTB executable. Budgets count selected physical candidates; exact expensive launches remain in the physical tool's durable attempt records. Remaining routed candidates are marked budget_deferred. The model is not refitted on calibration data after interval fitting. The shared project train() stub and main branch remain untouched.</p>
<h2>Verification and scope</h2><p>Sixteen deterministic checks verify separation of fit/calibration/test, exact 90% and 95% quantile ranks, interval nesting, familiar acceptance, unseen/size/wide-interval abstention, invalid-input review, ID/order preservation, absence of accepted values on abstention, physical budgets, and physical callback identity/count guards, and malformed/duplicate batch IDs. Exported routers also reproduce all 287 first-seed held-out predictions, intervals and routing decisions. Only mocked physical callbacks were used. Test predictions, split manifests, per-seed metrics, protocol, verification and models accompany the report.</p>
<p>The corpus remains small neutral closed-shell QM9-like molecules. Intervals target the xTB teacher rather than ORCA or experimental properties. Repeated seeds do not replace a prospective collaborator dataset or validate large conjugated emitters. The current default is deliberately conservative; it is an auditable prototype for ML triage rather than a certified confidence system.</p>
<h2>References</h2><p><a href="https://mapie.readthedocs.io/en/stable/content/conformal-prediction/split-cross-conformal/">MAPIE explanation of split conformal calibration and exchangeability</a> · <a href="https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html">scikit-learn ExtraTrees documentation</a></p></body></html>'''
(BASE/'Repeated_Splits_Uncertainty_Report.html').write_text(doc,encoding='utf-8')
readme='''# Five seeds and calibrated abstention

Open Repeated_Splits_Uncertainty_Report.html for plots and the full analysis.
Primary MAE mean ± sample SD: random 0.498 ± 0.026 eV; scaffold 0.517 ± 0.062 eV.
The separately calibrated 65% fit models have mean MAE 0.519 and 0.545 eV respectively.

Default inference artifact: models/random_calibrated_router.joblib, the first fixed seed.
It is calibrated on a separate subset and is not the earlier 85%-fit model.
Run router.py with --input id,smiles CSV and --output routes.json. Without
--run-physical it only writes a routing plan, with zero electronic calculations.
--run-physical requires the installed MolCurator package, --xyz-dir and an explicit
--physical-budget. No ORCA invocation is performed here. Deferred candidates remain visible.

Unfamiliar scaffolds, low similarity, out-of-scope size/elements or wide intervals route
to physical prediction. Unsupported inputs route to review. Abstention carries no
accepted ML value. The interval remains diagnostic, with an explicit coverage caveat.

Nominal normalized 90% empirical coverage was 87.7% random and 89.3% scaffold.
Acceptance filtering does not preserve a formal 90% coverage guarantee. All unseen
scaffold holdouts route to physical prediction under the strict default rule.
These limitations are retained; no test-driven threshold or method switch was made.

The source dataset is the earlier 948 successful labels out of 1000 attempted molecules.
No new xTB/ORCA calculations and no Git publishing were performed.
Install the versions in requirements.txt and keep features.py alongside router.py.
'''
(BASE/'README.md').write_text(readme,encoding='utf-8');
if not (BASE/'requirements.txt').exists():shutil.copyfile(BASE.parent/'molcurator-ml1000/requirements.txt',BASE/'requirements.txt')
print(summary.to_string(index=False));print(route_summary.to_string(index=False))
