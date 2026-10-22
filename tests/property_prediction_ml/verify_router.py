from pathlib import Path
import sys,json,math,csv
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1]
import numpy as np,pandas as pd
if __package__:
    from .features import describe
    from .router import CalibratedRouter,execute_routes
else:
    from features import describe
    from router import CalibratedRouter,execute_routes

def main(output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else BASE
    output_dir.mkdir(parents=True, exist_ok=True)
    router=CalibratedRouter(BASE/'models/random_calibrated_router.joblib');a=router.artifact
    assert not(set(a['training_ids'])&set(a['calibration_ids']) or set(a['training_ids'])&set(a['test_ids']) or set(a['calibration_ids'])&set(a['test_ids']))
    df=pd.read_csv(BASE/'labelled_dataset.csv' if (BASE/'labelled_dataset.csv').exists() else BASE.parent/'molcurator-ml1000/labelled_dataset.csv').set_index('candidate_id')
    cal=df.loc[a['calibration_ids']];xx=np.stack([describe(s)[0] for s in cal.smiles])
    trees=np.asarray([t.predict(xx) for t in a['estimator'].estimators_]);scores=abs(trees.mean(axis=0)-cal.xtb_gap_ev.to_numpy())/np.maximum(trees.std(axis=0),a['scale_floor_ev'])
    for coverage in [.90,.95]:
        k=math.ceil((len(scores)+1)*coverage);expected=float(np.sort(scores)[k-1])
        assert abs(expected-a['normalized_q'][str(coverage)])<1e-12
    familiar=a['training_smiles'][0]
    unseen=next(s for s in df.smiles if describe(s)[1] not in router.scaffolds)
    items=[dict(id='familiar',smiles=familiar),dict(id='unseen',smiles=unseen),dict(id='large',smiles='CCCCCCCCCCCCCCCC'),dict(id='invalid',smiles='not_a_smiles'),dict(id='radical',smiles='[CH3]'),dict(id='ion',smiles='[NH4+]')]
    rows=router.route(items)
    assert [r['candidate_id'] for r in rows]==[r['id'] for r in items]
    assert rows[0]['route']=='use_ml' and rows[0]['accepted_ml_value_ev'] is not None
    assert rows[1]['route']=='physical_predict' and 'unseen_scaffold' in rows[1]['reasons']
    assert rows[2]['route']=='physical_predict' and 'outside_size_scope' in rows[2]['reasons']
    assert all(r['accepted_ml_value_ev'] is None for r in rows[1:])
    assert all(r['route']=='input_review' for r in rows[3:])
    assert rows[0]['interval95_ev'][0]<=rows[0]['interval90_ev'][0]<=rows[0]['interval90_ev'][1]<=rows[0]['interval95_ev'][1]
    assert all(r['xyz_path'] is None for r in rows)
    assert router.route([])==[]
    for invalid_items in [[dict(id='same',smiles=familiar),dict(id='same',smiles=familiar)],[dict(smiles=familiar)],[dict(id='../unsafe',smiles=familiar)]]:
        try:router.route(invalid_items)
        except ValueError:pass
        else:raise AssertionError('invalid batch identity accepted')
    router.artifact['max_90_halfwidth_ev']=.001
    assert 'wide_interval' in router.route([items[0]])[0]['reasons']
    calls=[]
    def fake_physical(batch):
        calls.extend(batch)
        return [dict(candidate_id=r['id'],status='ok',value=4.2,xyz_path='fixture.xyz') for r in batch]
    result=execute_routes(rows,fake_physical,1)
    assert [r['id'] for r in calls]==['unseen']
    assert result[1]['physical_status']=='ok' and result[2]['physical_status']=='budget_deferred'
    assert 'physical_status' not in rows[1]
    calls.clear();execute_routes(rows,fake_physical,0);assert not calls
    for budget in [-1,True,1.5]:
        try:execute_routes(rows,fake_physical,budget)
        except ValueError:pass
        else:raise AssertionError('invalid budget accepted')
    try:execute_routes(rows,lambda b:[],1)
    except ValueError:pass
    else:raise AssertionError('missing physical outputs accepted')
    try:execute_routes(rows,lambda b:[dict(candidate_id='wrong',status='ok')],1)
    except ValueError:pass
    else:raise AssertionError('wrong physical ID accepted')
    (output_dir/'routing_example.csv').write_text('id,smiles\n'+'\n'.join(f"{r['id']},{r['smiles']}" for r in items)+'\n')
    (output_dir/'routing_example.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
    checks=dict(calibration_fit_test_disjoint=True,quantile_rank_90_95_verified=True,interval_nesting=True,familiar_acceptance=True,unseen_scaffold_abstention=True,size_abstention=True,wide_interval_abstention=True,invalid_radical_ion_review=True,ids_order_preserved=True,batch_id_guards=True,abstention_has_no_accepted_value=True,physical_budget_enforced=True,zero_budget_no_calls=True,physical_id_count_guards=True,input_plan_not_mutated=True,no_live_electronic_calls=True)
    (output_dir/'verification.json').write_text(json.dumps(checks,indent=2));print('All',len(checks),'routing/calibration checks passed')
if __name__=='__main__':main()
