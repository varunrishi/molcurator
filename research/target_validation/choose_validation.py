#!/usr/bin/env python3
"""Stratified probability-sample of xTB-screened candidates. Calibrations FROZEN."""
import argparse,csv,json,random,math
from collections import Counter
from pathlib import Path
OFFSET=2.2617441034023127
# Strata based on corrected gap distance to [3,3.5], independent of ORCA labels.
def stratum(x):
 d=max(3.0-x,0,x-3.5)
 if d<=.2:return 'near_0_0p2'
 if d<=.5:return 'shoulder_0p2_0p5'
 if d<=1:return 'moderate_0p5_1'
 if d<=2:return 'far_1_2'
 return 'far_gt_2'

def main():
 p=argparse.ArgumentParser();p.add_argument('--screened',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--n',type=int,default=60);p.add_argument('--seed',type=int,default=217);p.add_argument('--offset',type=float,default=OFFSET);a=p.parse_args()
 if a.output.exists():raise SystemExit('Refusing to overwrite validation manifest')
 if not math.isfinite(a.offset):raise SystemExit('Bad offset')
 with a.screened.open() as f:rows=list(csv.DictReader(f))
 groups={s:[] for s in ('near_0_0p2','shoulder_0p2_0p5','moderate_0p5_1','far_1_2','far_gt_2')}
 ids=set()
 for row in rows:
  if row['candidate_id'] in ids:raise SystemExit('Duplicate candidate ID')
  ids.add(row['candidate_id'])
  if row['status']!='ok':continue
  x=float(row['xtb_gap_ev']);row['corrected_gap_ev']=x+a.offset;row['stratum']=stratum(row['corrected_gap_ev']);groups[row['stratum']].append(row)
 if len(groups['near_0_0p2'])==0:print('WARNING: no candidates near target; recall estimation may remain impossible')
 # Allocate a nonzero sample from every nonempty stratum; overallocate near-window.
 desired=[.40,.23,.17,.10,.10];names=list(groups)
 alloc={k:0 for k in names};remaining=min(a.n,sum(len(v) for v in groups.values()))
 # pass 1: guarantee >=1 per nonempty stratum
 for k in names:
  if groups[k] and remaining:alloc[k]+=1;remaining-=1
 # pass 2: demand-weighted fair allocation respecting capacities
 while remaining:
  possible=[k for k in names if alloc[k]<len(groups[k])]
  if not possible:break
  k=max(possible,key=lambda key:(desired[names.index(key)]*a.n-alloc[key],-names.index(key)))
  alloc[k]+=1;remaining-=1
 rng=random.Random(a.seed);chosen=[]
 for name in names:
  group=groups[name];rng.shuffle(group);N=len(group);n=alloc[name]
  for row in group[:n]:
   chosen.append({**row,'stratum_population':N,'stratum_selected':n,'selection_probability':n/N,'inverse_probability_weight':N/n})
 rng.shuffle(chosen)
 a.output.parent.mkdir(parents=True,exist_ok=True)
 cols=['candidate_id','smiles','xtb_gap_ev','corrected_gap_ev','xyz_path','stratum','stratum_population','stratum_selected','selection_probability','inverse_probability_weight']
 with a.output.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(chosen)
 print(json.dumps({'selected':len(chosen),'strata':{k:{'pool':len(groups[k]),'sample':alloc[k]} for k in names}},indent=2))
 print('Important: selected IDs and probabilities are frozen. Do not cherry-pick validation outcomes.')
if __name__=='__main__':main()
