#!/usr/bin/env python3
"""One prospective molecule: FF minimum -> xTB only; no ORCA."""
import argparse,csv,json,sys
from pathlib import Path
from molcurator.schemas import Candidate,PropertyTarget,Status
from molcurator.tools.predict import predict
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--index',type=int,required=True);a=p.parse_args()
with a.manifest.open() as f: rows=list(csv.DictReader(f))
if a.index<0 or a.index>=len(rows):raise SystemExit('Invalid array index')
r=rows[a.index];dest=a.out/r['candidate_id'];dest.mkdir(parents=True,exist_ok=True);path=dest/'screen.json'
if path.exists():
 try:
  if json.loads(path.read_text()).get('status')=='ok':sys.exit(0)
 except (ValueError,OSError):pass
record={**r,'status':'failed','xtb_gap_ev':None,'error':None,'xyz_path':None}
try:
 c=Candidate(id=r['candidate_id'],smiles=r['smiles'],parent_smiles=r['smiles'],round=1,generator='prospective_pool')
 pred=predict([c],PropertyTarget(name='homo_lumo_gap',min=0),dest/'xyz')[0]
 record.update(status=pred.status.value,xtb_gap_ev=pred.value,error=pred.error,xyz_path=str(pred.xyz_path) if pred.xyz_path else None)
except Exception as exc:record['error']=f'{type(exc).__name__}: {exc}'
path.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if record['status']!='ok':sys.exit(1)
