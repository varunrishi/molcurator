#!/usr/bin/env python3
"""Collect fixed split, compare raw, train-only offset & linear corrections."""
import argparse,csv,json,math
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
with a.manifest.open() as f:rows=list(csv.DictReader(f))
for row in rows:
 f=a.out/row['candidate_id']/'result.json'
 if f.exists():
  try: row.update(json.loads(f.read_text()))
  except (OSError,ValueError) as e:row.update(status='invalid_result',error=str(e))
 else:row.update(status='missing',error='not run')
cols=['candidate_id','smiles','group','split','method','xtb_gap_ev','orca_gap_ev','status','error','qm_calls_attempted']
a.out.mkdir(parents=True,exist_ok=True)
with (a.out/'all_results.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
valid=[r for r in rows if r.get('status')=='ok' and r.get('xtb_gap_ev') is not None and r.get('orca_gap_ev') is not None]
train=[r for r in valid if r['split']=='train'];test=[r for r in valid if r['split']=='test']
summary=dict(n_total=len(rows),n_success=len(valid),n_train=len(train),n_test=len(test),n_failed=sum(r.get('status')=='failed' for r in rows),n_missing=sum(r.get('status')=='missing' for r in rows),qm_calls_attempted=sum(int(r.get('qm_calls_attempted') or 0) for r in rows))
print(summary)
if len(train)<8 or len(test)<4:
 print('Not enough independent data for test metrics; collection saved, no calibration assessed.')
 (a.out/'metrics.json').write_text(json.dumps({'status':'insufficient_data',**summary},indent=2)+'\n')
 raise SystemExit(0)
x=np.array([float(r['xtb_gap_ev']) for r in train]);y=np.array([float(r['orca_gap_ev']) for r in train]);
offset=float(np.mean(y-x)); slope,intercept=[float(v) for v in np.polyfit(x,y,1)]
xt=np.array([float(r['xtb_gap_ev']) for r in test]); yt=np.array([float(r['orca_gap_ev']) for r in test]);
methods={'raw_xtb':xt,'constant_offset':xt+offset,'linear':slope*xt+intercept}
metrics={'status':'ok',**summary,'train_offset_ev':offset,'train_linear_slope':slope,'train_linear_intercept_ev':intercept,'held_out':{}}
for name,pred in methods.items():
 err=pred-yt
 metrics['held_out'][name]=dict(mae_ev=float(np.mean(abs(err))),rmse_ev=float(np.sqrt(np.mean(err**2))),bias_ev=float(np.mean(err)))
# Explicit counts for configured target [3.0,3.5] and margin 0.2; these can be zero without valid recall.
lo,hi,margin=3.0,3.5,0.2
eligible=(yt>=lo)&(yt<=hi)
for name,pred in methods.items():
 selected=(pred>=lo-margin)&(pred<=hi+margin)
 metrics['held_out'][name].update(true_in_window=int(eligible.sum()),screened_in=int(selected.sum()),false_negatives=int((eligible & ~selected).sum()),recall=(float(np.mean(selected[eligible])) if eligible.any() else None))
(a.out/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
with (a.out/'test_predictions.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['candidate_id','group','xtb_ev','orca_ev','raw_ev','offset_ev','linear_ev'])
 for i,r in enumerate(test):w.writerow([r['candidate_id'],r['group'],xt[i],yt[i],methods['raw_xtb'][i],methods['constant_offset'][i],methods['linear'][i]])
print(json.dumps(metrics,indent=2))
