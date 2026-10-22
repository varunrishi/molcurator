"""Five fixed seeded repeats and separate calibration. No electronic calculations."""
from pathlib import Path
import sys,json,time,math,hashlib,shutil
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1];PREV=BASE.parent/'molcurator-ml1000'
import numpy as np,pandas as pd,joblib
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.model_selection import train_test_split,GroupShuffleSplit
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from threadpoolctl import threadpool_limits
from rdkit import Chem,DataStructs,rdBase
if __package__:
    from .features import describe,FP_SIZE
else:
    from features import describe,FP_SIZE
thread_limit=threadpool_limits(limits=2)
BASE.mkdir(exist_ok=True);(BASE/'models').mkdir(exist_ok=True)
SEEDS=[20261022,20261023,20261024,20261025,20261026]
protocol=dict(seeds=SEEDS,n_estimators=160,max_features=.7,min_samples_leaf=1,model_and_partition_seed_varied=True,baseline_development_fraction=.85,calibrated_fit_fraction=.65,calibration_fraction=.20,test_fraction=.15,hyperparameters_fixed_from_previous_experiment=True,nominal_coverages=[.90,.95],scale_floor_ev=.10,similarity_cutoff='max(0.25, 10th percentile of fit-only leave-one-out nearest similarity)',unseen_scaffold_abstains=True,maximum_90_interval_halfwidth_ev=1.0,deployment='first random seed fixed before tests; no best-seed selection',no_new_electronic_calculations=True)
(BASE/'protocol.json').write_text(json.dumps(protocol,indent=2))
DATA=BASE/'labelled_dataset.csv' if (BASE/'labelled_dataset.csv').exists() else PREV/'labelled_dataset.csv'
df=pd.read_csv(DATA);X=[];groups=[];fps=[]
for s in df.smiles:
    x,g,fp=describe(s);X.append(x);groups.append(g);fps.append(fp)
X=np.asarray(X);groups=np.asarray(groups);y=df.xtb_gap_ev.to_numpy();idx=np.arange(len(y))
assert len(set(df.connectivity_key))==len(df)
if not (BASE/'features.py').exists():shutil.copyfile(PREV/'features.py',BASE/'features.py')

def quantile(scores,coverage):
    scores=np.asarray(scores,dtype=float);k=math.ceil((len(scores)+1)*coverage)
    return float(np.sort(scores)[k-1]) if 1<=k<=len(scores) else float('inf')
def predict_scale(model,xx):
    tree=np.asarray([e.predict(xx) for e in model.estimators_]);return tree.mean(axis=0),np.maximum(tree.std(axis=0),.10)
def model(seed):return ExtraTreesRegressor(n_estimators=160,min_samples_leaf=1,max_features=.7,random_state=seed,n_jobs=2)
def partition(seed,kind):
    if kind=='random':
        dev,test=train_test_split(idx,test_size=.15,random_state=seed)
        fit,cal=train_test_split(dev,test_size=.20/.85,random_state=seed+500)
        return dev,fit,cal,test,0
    options=[]
    for a in range(100):
        dev,test=next(GroupShuffleSplit(n_splits=1,test_size=.15,random_state=seed+1000*a).split(idx,groups=groups))
        fit0,cal0=next(GroupShuffleSplit(n_splits=1,test_size=.20/.85,random_state=seed+500+1000*a).split(dev,groups=groups[dev]))
        fit,cal=dev[fit0],dev[cal0]
        options.append((abs(len(test)/len(idx)-.15)+abs(len(cal)/len(idx)-.20),a,dev,fit,cal,test))
    _,a,dev,fit,cal,test=min(options,key=lambda t:t[0]);return dev,fit,cal,test,a
results=[];intervals=[];predictions=[];manifests=[];routing=[];audit=[]
started=time.perf_counter()
for kind in ['random','scaffold']:
 for seed in SEEDS:
    dev,fit,cal,test,offset=partition(seed,kind)
    assert set(fit)|set(cal)==set(dev)
    assert not(set(fit)&set(cal) or set(dev)&set(test))
    if kind=='scaffold':assert not(set(groups[fit])&set(groups[cal]) or set(groups[dev])&set(groups[test]))
    for part,ii in [('fit',fit),('calibration',cal),('test',test)]:
        manifests.extend(dict(kind=kind,seed=seed,partition=part,candidate_id=df.iloc[i].candidate_id,scaffold=groups[i]) for i in ii)
    baseline=model(seed);baseline.fit(X[dev],y[dev]);bp=baseline.predict(X[test])
    calibrated=model(seed);calibrated.fit(X[fit],y[fit]);cp,cs=predict_scale(calibrated,X[cal]);tp,ts=predict_scale(calibrated,X[test])
    for name,pp,nfit in [('baseline_85pct',bp,len(dev)),('calibrated_65pct',tp,len(fit))]:
        results.append(dict(kind=kind,seed=seed,model=name,n_fit=nfit,n_calibration=len(cal) if name.startswith('calibrated') else 0,n_test=len(test),mae_ev=mean_absolute_error(y[test],pp),rmse_ev=mean_squared_error(y[test],pp)**.5,r2=r2_score(y[test],pp)))
    fitfps=[fps[i] for i in fit]
    loo=[]
    for j,fp in enumerate(fitfps):
        sim=DataStructs.BulkTanimotoSimilarity(fp,fitfps);sim[j]=-1;loo.append(max(sim))
    threshold=max(.25,float(np.quantile(loo,.10)))
    nearest=np.asarray([max(DataStructs.BulkTanimotoSimilarity(fps[i],fitfps)) for i in test])
    fit_scaffolds=set(groups[fit]);heavy_min=int(df.iloc[fit].heavy_atoms.min());heavy_max=int(df.iloc[fit].heavy_atoms.max())
    abs_scores=abs(y[cal]-cp);norm_scores=abs_scores/cs
    qvalues={};groupvalues={}
    for coverage in [.9,.95]:
        q=quantile(norm_scores,coverage);qa=quantile(abs_scores,coverage);qvalues[str(coverage)]=q
        group_max=[float(max(norm_scores[groups[cal]==g])) for g in set(groups[cal])]
        qg=quantile(group_max,coverage);groupvalues[str(coverage)]=qg
        for method,half in [('absolute',np.full(len(test),qa)),('normalized',q*ts),('group_max_normalized',qg*ts)]:
            covered=abs(y[test]-tp)<=half
            group_covered=[bool(np.all(covered[groups[test]==g])) for g in set(groups[test])]
            intervals.append(dict(kind=kind,seed=seed,method=method,nominal_coverage=coverage,n_calibration=len(cal),n_calibration_groups=len(set(groups[cal])),n_test=len(test),empirical_molecule_coverage=float(covered.mean()),empirical_complete_group_coverage=float(np.mean(group_covered)),mean_width_ev=float(np.mean(2*half)),q=q if method=='normalized' else qa if method=='absolute' else qg))
    # Policy fixed before testing. Intervals are not tuned after observing coverage.
    q90=qvalues['0.9'];half90=q90*ts;reason_rows=[]
    for k,i in enumerate(test):
        reasons=[]
        if groups[i] not in fit_scaffolds:reasons.append('unseen_scaffold')
        if nearest[k]<threshold:reasons.append('low_similarity')
        if not heavy_min<=df.iloc[i].heavy_atoms<=heavy_max:reasons.append('outside_size_scope')
        if half90[k]>1.:reasons.append('wide_interval')
        if tp[k]<0:reasons.append('negative_gap_estimate')
        reason_rows.append(reasons)
        predictions.append(dict(kind=kind,seed=seed,candidate_id=df.iloc[i].candidate_id,smiles=df.iloc[i].smiles,scaffold=groups[i],xtb_gap_ev=y[i],baseline_prediction_ev=bp[k],calibrated_prediction_ev=tp[k],lower90_ev=tp[k]-half90[k],upper90_ev=tp[k]+half90[k],scale_ev=ts[k],nearest_fit_tanimoto=nearest[k],similarity_threshold=threshold,route='physical_predict' if reasons else 'use_ml',reasons=';'.join(reasons)))
    accept=np.asarray([not r for r in reason_rows]);err=abs(tp-y[test])
    routing.append(dict(kind=kind,seed=seed,n_test=len(test),accepted_ml=int(accept.sum()),routed_physical=int((~accept).sum()),accepted_fraction=float(accept.mean()),accepted_mae_ev=float(err[accept].mean()) if accept.any() else None,routed_mae_ev=float(err[~accept].mean()) if (~accept).any() else None,accepted_interval90_coverage=float((err[accept]<=half90[accept]).mean()) if accept.any() else None,similarity_threshold=threshold,unseen_scaffold=int(sum('unseen_scaffold' in r for r in reason_rows)),low_similarity=int(sum('low_similarity' in r for r in reason_rows)),wide_interval=int(sum('wide_interval' in r for r in reason_rows))))
    audit.append(dict(kind=kind,seed=seed,fit_calibration_test_disjoint=True,scaffold_disjoint=kind=='scaffold',group_balance_seed_offset=offset))
    if seed==SEEDS[0]:
        artifact=dict(format='molcurator-calibrated-routing-v1',estimator=calibrated,seed=seed,partition_kind=kind,target='homo_lumo_gap',units='eV',reference_method='GFN2-xTB on selected MMFF94 geometry',training_ids=df.iloc[fit].candidate_id.tolist(),calibration_ids=df.iloc[cal].candidate_id.tolist(),test_ids=df.iloc[test].candidate_id.tolist(),training_smiles=df.iloc[fit].smiles.tolist(),training_scaffolds=sorted(fit_scaffolds),heavy_atom_range=[heavy_min,heavy_max],allowed_elements=sorted({a.GetAtomicNum() for s in df.iloc[fit].smiles for a in Chem.MolFromSmiles(s).GetAtoms()}),similarity_threshold=threshold,scale_floor_ev=.10,normalized_q=qvalues,group_max_q=groupvalues,max_90_halfwidth_ev=1.,require_known_scaffold=True,rdkit=rdBase.rdkitVersion,calibration_caveat='Marginal exchangeability assumptions do not imply coverage on new scaffolds or conditional coverage after selection')
        joblib.dump(artifact,BASE/'models'/f'{kind}_calibrated_router.joblib',compress=3)
    pd.DataFrame(results).to_csv(BASE/'repeat_metrics.csv',index=False);pd.DataFrame(intervals).to_csv(BASE/'interval_metrics.csv',index=False);pd.DataFrame(routing).to_csv(BASE/'routing_metrics.csv',index=False)
    print(kind,seed,'baseline MAE',round(results[-2]['mae_ev'],4),'calibrated MAE',round(results[-1]['mae_ev'],4),'accepted',int(accept.sum()),'/',len(test),flush=True)
pd.DataFrame(predictions).to_csv(BASE/'test_predictions.csv',index=False);pd.DataFrame(manifests).to_csv(BASE/'split_manifest.csv',index=False)
pd.DataFrame(results).groupby(['kind','model']).agg(mae_mean_ev=('mae_ev','mean'),mae_sd_ev=('mae_ev','std'),mae_min_ev=('mae_ev','min'),mae_max_ev=('mae_ev','max'),rmse_mean_ev=('rmse_ev','mean'),r2_mean=('r2','mean'),n_repeats=('seed','count')).reset_index().to_csv(BASE/'repeat_summary.csv',index=False)
(BASE/'audit.json').write_text(json.dumps(dict(n= len(df),seeds=SEEDS,checks=audit,wall_s=time.perf_counter()-started,input_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),new_electronic_calls=0),indent=2))
print('Study complete',flush=True)
