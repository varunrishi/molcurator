"""Calibrated ML triage. Abstention never silently becomes an accepted prediction."""
from pathlib import Path
import sys,json,csv,argparse,re
BASE=Path(__file__).resolve().parent
import joblib,numpy as np
from rdkit import Chem,DataStructs
if __package__:
    from .features import describe,FP_SIZE
else:
    from features import describe,FP_SIZE

class CalibratedRouter:
    def __init__(self,path):
        self.artifact=joblib.load(path)
        a=self.artifact
        if a.get('format')!='molcurator-calibrated-routing-v1':raise ValueError('unsupported calibrated model')
        self.fps=[describe(s)[2] for s in a['training_smiles']]
        self.scaffolds=set(a['training_scaffolds'])
        self.allowed=set(a['allowed_elements'])|{1}
    def route(self,items):
        ids=[item.get('id',item.get('candidate_id')) for item in items]
        if any(not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',cid) for cid in ids):
            raise ValueError('each row requires a nonempty safe molecule ID')
        if len(ids)!=len(set(ids)):raise ValueError('molecule IDs must be unique within the batch')
        result=[];valid=[];matrix=[]
        for item in items:
            cid=item.get('id',item.get('candidate_id'));row=dict(candidate_id=cid,smiles=item.get('smiles'),status='failed',route='input_review',accepted_ml_value_ev=None,ml_estimate_ev=None,xyz_path=None,reasons=[],units='eV')
            try:
                x,g,fp=describe(item['smiles']);mol=Chem.MolFromSmiles(item['smiles'])
                reasons=[];similarity=max(DataStructs.BulkTanimotoSimilarity(fp,self.fps))
                if self.artifact['require_known_scaffold'] and g not in self.scaffolds:reasons.append('unseen_scaffold')
                if similarity<self.artifact['similarity_threshold']:reasons.append('low_similarity')
                if not self.artifact['heavy_atom_range'][0]<=x[FP_SIZE+8]<=self.artifact['heavy_atom_range'][1]:reasons.append('outside_size_scope')
                if any(a.GetAtomicNum() not in self.allowed for a in mol.GetAtoms()):reasons.append('outside_elements_scope')
                row.update(reasons=reasons,nearest_fit_tanimoto=similarity,similarity_threshold=self.artifact['similarity_threshold'],scaffold=g,reference_method=self.artifact['reference_method'])
                valid.append(len(result));matrix.append(x)
            except Exception as exc:row.update(error=f'{type(exc).__name__}: {exc}',reasons=['invalid_or_unsupported_input'])
            result.append(row)
        if valid:
            estimates=np.asarray([t.predict(np.asarray(matrix)) for t in self.artifact['estimator'].estimators_]);mean=estimates.mean(axis=0);scale=np.maximum(estimates.std(axis=0),self.artifact['scale_floor_ev'])
            for k,i in enumerate(valid):
                row=result[i];value=float(mean[k]);half90=float(self.artifact['normalized_q']['0.9']*scale[k]);half95=float(self.artifact['normalized_q']['0.95']*scale[k])
                if not np.isfinite([value,half90,half95]).all():
                    row.update(status='failed',route='input_review',error='nonfinite model output',reasons=['nonfinite_output']);continue
                if half90>self.artifact['max_90_halfwidth_ev']:row['reasons'].append('wide_interval')
                if value<0:row['reasons'].append('negative_gap_estimate')
                row.update(ml_estimate_ev=value,interval90_ev=[value-half90,value+half90],interval95_ev=[value-half95,value+half95],interval_method='normalized split conformal',coverage_caveat='Marginal calibration does not guarantee coverage under scaffold shift or after acceptance filtering')
                if row['reasons']:row.update(status='abstain',route='physical_predict')
                else:row.update(status='ok',route='use_ml',accepted_ml_value_ev=value)
        return result

def execute_routes(routes,physical_predict,physical_budget):
    """Run only explicitly budgeted physical candidates; callback takes ordered id/smiles rows.

    Physical results are attached beside ML diagnostics. ORCA is never called here.
    """
    if isinstance(physical_budget,bool) or not isinstance(physical_budget,int) or physical_budget<0:raise ValueError('physical_budget must be a nonnegative integer')
    result=[dict(row) for row in routes]
    eligible=[i for i,r in enumerate(result) if r['route']=='physical_predict'];selected=eligible[:physical_budget]
    for i in eligible:result[i]['physical_status']='budget_deferred'
    if selected:
        physical=physical_predict([dict(id=result[i]['candidate_id'],smiles=result[i]['smiles']) for i in selected])
        if len(physical)!=len(selected):raise ValueError('physical callback must preserve result count')
        for i,p in zip(selected,physical):
            if p.get('candidate_id')!=result[i]['candidate_id']:raise ValueError('physical callback must preserve IDs and order')
            result[i].update(physical_status=p['status'],physical_result=p)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--run-physical',action='store_true');p.add_argument('--physical-budget',type=int,default=0);p.add_argument('--xyz-dir',type=Path);a=p.parse_args()
    if a.physical_budget<0:p.error('--physical-budget must be nonnegative')
    if a.run_physical and a.xyz_dir is None:p.error('--xyz-dir is required with --run-physical')
    with a.input.open() as f:items=list(csv.DictReader(f))
    routes=CalibratedRouter(a.model).route(items)
    if a.run_physical:
        from molcurator.schemas import Candidate,PropertyTarget
        from molcurator.tools.predict import predict
        def physics(rows):
            candidates=[Candidate(id=r['id'],smiles=r['smiles'],parent_smiles=r['smiles'],round=1,generator='ml_abstention') for r in rows]
            return [r.model_dump(mode='json') for r in predict(candidates,PropertyTarget(name='homo_lumo_gap',min=0,units='eV'),a.xyz_dir)]
        routes=execute_routes(routes,physics,a.physical_budget)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(routes,indent=2,allow_nan=False),encoding='utf-8')
    print(f'{len(routes)} rows; {sum(r["route"]=="use_ml" for r in routes)} ML accepted; {sum(r["route"]=="physical_predict" for r in routes)} physical routes; physical execution {a.run_physical}')
if __name__=='__main__':main()
