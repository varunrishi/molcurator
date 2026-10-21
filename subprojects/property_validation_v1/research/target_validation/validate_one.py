#!/usr/bin/env python3
"""Validate the precomputed xTB XYZ; never repeat xTB or geometry generation."""
import argparse,csv,json,sys
from pathlib import Path
from molcurator.schemas import Prediction,PropertyTarget,QMSettings,Status
from molcurator_property_validation.tools.validate import validate
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--index',type=int,required=True);a=p.parse_args()
with a.manifest.open() as f:rows=list(csv.DictReader(f))
if not 0<=a.index<len(rows):raise SystemExit('Bad index')
r=rows[a.index];dest=a.out/r['candidate_id'];dest.mkdir(parents=True,exist_ok=True);path=dest/'validation.json'
if path.exists():
 try:
  if json.loads(path.read_text()).get('status')=='ok':sys.exit(0)
 except (ValueError,OSError):pass
record={**r,'status':'failed','orca_gap_ev':None,'error':None,'qm_calls_attempted':0,'method':'dft:B3LYP/def2-SVP'}
try:
 xyz=Path(r['xyz_path']).resolve()
 if not xyz.is_file():raise FileNotFoundError(f'Missing screened XYZ: {xyz}')
 pred=Prediction(candidate_id=r['candidate_id'],status=Status.ok,value=float(r['xtb_gap_ev']),xyz_path=xyz)
 result=validate([pred],PropertyTarget(name='homo_lumo_gap',min=0),QMSettings(backend='orca',functional='B3LYP',basis='def2-SVP'))[0]
 attempt=xyz.parent/'calculations'/r['candidate_id']/'orca'/'attempt.json'
 if attempt.exists():record['qm_calls_attempted']=int(json.loads(attempt.read_text()).get('qm_calls_attempted',0))
 record.update(status=result.status.value,orca_gap_ev=result.value,error=result.error)
except Exception as exc:record['error']=f'{type(exc).__name__}: {exc}'
path.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if record['status']!='ok':sys.exit(1)
