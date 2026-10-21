#!/usr/bin/env python3
import argparse,csv,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
with a.manifest.open() as f:rows=list(csv.DictReader(f))
for r in rows:
    path=a.out/r['candidate_id']/'screen.json'
    if path.exists():
        try:r.update(json.loads(path.read_text()))
        except Exception as exc:r.update(status='invalid',error=str(exc))
    else:r.update(status='missing',error='not started')
cols=['candidate_id','smiles','status','xtb_gap_ev','xyz_path','error']
a.out.mkdir(parents=True,exist_ok=True)
with (a.out/'screened.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
from collections import Counter
print(dict(Counter(r['status'] for r in rows)))
