#!/usr/bin/env python3
"""Run precisely one existing contract-adapter predict -> validate pair."""
import argparse,csv,json,os,sys,traceback
from pathlib import Path
from molcurator.schemas import Candidate,PropertyTarget,QMSettings,Status
from molcurator_property_validation.tools.predict import predict
from molcurator_property_validation.tools.validate import validate
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--index',type=int,required=True);a=p.parse_args()
with a.manifest.open() as f: rows=list(csv.DictReader(f))
if not (0<=a.index<len(rows)): raise SystemExit(f'Index {a.index} outside 0..{len(rows)-1}')
r=rows[a.index]; dest=a.out/r['candidate_id'];dest.mkdir(parents=True,exist_ok=True)
result_path=dest/'result.json'
if result_path.exists():
 try:
  prior=json.loads(result_path.read_text())
  if prior.get('status')=='ok':
   print(f"Completed already: {r['candidate_id']}");sys.exit(0)
 except (ValueError,OSError): pass
candidate=Candidate(id=r['candidate_id'],smiles=r['smiles'],parent_smiles=r['smiles'],round=1,generator='calibration_panel')
target=PropertyTarget(name='homo_lumo_gap',min=0.0)
qm=QMSettings(backend='orca',functional='B3LYP',basis='def2-SVP')
payload={**r,'method':'dft:B3LYP/def2-SVP','xtb_gap_ev':None,'orca_gap_ev':None,'status':'failed','error':None,'qm_calls_attempted':0}
try:
 preds=predict([candidate],target,dest/'xyz')
 pred=preds[0]
 if pred.status is Status.ok: payload['xtb_gap_ev']=pred.value
 else: raise RuntimeError(f'xTB: {pred.error}')
 # Note budget: exactly one validate invocation; validate writes attempt.json.
 res=validate(preds,target,qm)[0]
 attempt=dest/'xyz'/'calculations'/r['candidate_id']/'orca'/'attempt.json'
 if attempt.exists(): payload['qm_calls_attempted']=json.loads(attempt.read_text()).get('qm_calls_attempted',0)
 if res.status is Status.ok:
  payload['orca_gap_ev']=res.value;payload['status']='ok'
 else: raise RuntimeError(f'ORCA: {res.error}')
except Exception as exc:
 payload['error']=f'{type(exc).__name__}: {exc}'
finally:
 result_path.write_text(json.dumps(payload,indent=2)+'\n')
 print(json.dumps(payload,indent=2))
if payload['status']!='ok':sys.exit(1)
