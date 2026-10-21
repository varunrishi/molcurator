#!/usr/bin/env python3
"""Prospective stratified evaluation, with Horvitz-Thompson estimates and unweighted sample metrics."""
import argparse,csv,json,math
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--margin',type=float,nargs='*',default=[.2,.5,.75,1.,1.5]);a=p.parse_args()
with a.manifest.open() as f:rows=list(csv.DictReader(f))
for r in rows:
 path=a.out/r['candidate_id']/'validation.json'
 if path.exists():
  try:r.update(json.loads(path.read_text()))
  except Exception as e:r.update(status='invalid',error=str(e))
 else:r.update(status='missing',error='not run')
cols=list(dict.fromkeys([k for r in rows for k in r]));a.out.mkdir(parents=True,exist_ok=True)
with (a.out/'validation_results.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
ok=[r for r in rows if r['status']=='ok' and r.get('orca_gap_ev') is not None]
summary={'n_selected':len(rows),'n_success':len(ok),'n_missing':sum(r['status']=='missing' for r in rows),'n_failed':sum(r['status']=='failed' for r in rows),'qm_calls_attempted_from_records':sum(int(r.get('qm_calls_attempted') or 0) for r in rows)}
if len(ok)!=len(rows):
 summary['status']='incomplete';(a.out/'screening_metrics.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));raise SystemExit('Validation incomplete: no weighted claims yet')
x=np.array([float(r['xtb_gap_ev']) for r in ok]);y=np.array([float(r['orca_gap_ev']) for r in ok]);w=np.array([float(r['inverse_probability_weight']) for r in ok]);truth=(y>=3.)&(y<=3.5)
# All selected have known inclusion probabilities; corrected gap coefficient was frozen from previous calibration24.
models={'raw_xtb':x,'constant_offset':x+2.2617441034023127,'linear_24':.8270780546046135*x+2.9901896256531098}
summary.update(status='ok',n_true_hits=int(truth.sum()),estimated_pool_hits=float(np.sum(w*truth)),pool_size_estimated_from_weights=float(w.sum()),models={})
for name,pred in models.items():
 d=pred-y
 out={'sample_mae_ev':float(np.mean(np.abs(d))),'weighted_pool_mae_ev':float(np.average(np.abs(d),weights=w)),'margins':{}}
 for margin in a.margin:
  screen=(pred>=3.-margin)&(pred<=3.5+margin)
  hits=truth&screen
  result={'sample_selected':int(screen.sum()),'sample_true_positives':int(hits.sum()),'sample_false_negatives':int((truth&~screen).sum()),'sample_recall':float(hits.sum()/truth.sum()) if truth.sum() else None,
          'estimated_pool_selected':float(np.sum(w*screen)), 'estimated_pool_hits':float(np.sum(w*truth)),
          'weighted_hit_recall':float(np.sum(w*hits)/np.sum(w*truth)) if np.sum(w*truth)>0 else None}
  out['margins'][str(margin)]=result
 summary['models'][name]=out
(a.out/'screening_metrics.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
