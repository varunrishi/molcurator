"""Generated-molecule property predictor: backend dispatch, data and contract behavior."""
import json
from pathlib import Path

import pytest

from molcurator.schemas import Candidate, Prediction, PropertyTarget, QMSettings, Status
from molcurator_property_validation import PredictorSettings, PropertyPredictor, predict_properties
from molcurator_property_validation import predictor
from molcurator_property_validation.ml import FingerprintModel, train_fingerprint_model
from molcurator_property_validation.properties import extract_properties

XYZ = '2\nH2\nH 0 0 0\nH 0 0 .74\n'
XTB = '''GEOMETRY OPTIMIZATION CONVERGED
 1 2.0000 -0.3 -8.0 (HOMO)
 2 -0.1 -3.0 (LUMO)
HOMO-LUMO GAP 5.0 eV
molecular dipole:
 full: 0.0 0.0 0.5 1.25
normal termination of xtb
'''
ORCA = '''SCF CONVERGED AFTER 5 CYCLES
ORBITAL ENERGIES
 0 2.0000 -0.3 -8.0
 1 0.0000 -0.1 -3.0

DIPOLE MOMENT
Magnitude (Debye) : 1.5
ORCA TERMINATED NORMALLY
'''


def molecule(cid='generated-1', smiles='[H][H]'):
    return Candidate(id=cid, smiles=smiles, parent_smiles=smiles, round=1, generator='test')


def train(path):
    model = train_fingerprint_model(['CCO', 'CC', 'CCC', 'CO'],
        {'homo_lumo_gap': [5., 7., 6., 5.5]}, reference_method='dft:B3LYP/def2-SVP')
    model.save(path)
    return model


@pytest.mark.parametrize('backend,text,dipole', [('xtb', XTB, 1.25), ('orca', ORCA, 1.5)])
def test_extract_real_fields(backend, text, dipole):
    assert extract_properties(text, backend) == dict(homo=-8., lumo=-3., homo_lumo_gap=5., dipole=dipole)


def test_xtb_mixed_molecules_all_properties(tmp_path, monkeypatch):
    def xtb(items, target, xyz_dir):
        c = items[0]
        if c.id == 'bad':
            return [Prediction(candidate_id=c.id, status=Status.failed, error='xTB timeout')]
        folder = xyz_dir / 'calculations' / c.id / 'xtb'
        folder.mkdir(parents=True)
        (folder / 'xtb.out').write_text(XTB)
        xyz = xyz_dir / f'{c.id}.xyz'
        xyz.write_text(XYZ)
        return [Prediction(candidate_id=c.id, status=Status.ok, value=5, xyz_path=xyz)]
    monkeypatch.setattr(predictor, 'xtb_predict', xtb)
    results = predict_properties([molecule(), molecule('bad'), molecule('last')],
        PredictorSettings(properties=['homo', 'lumo', 'homo_lumo_gap', 'dipole']), tmp_path/'out')
    assert [r.candidate_id for r in results] == ['generated-1', 'bad', 'last']
    assert [r.status for r in results] == [Status.ok, Status.failed, Status.ok]
    assert results[0].units['dipole'] == 'D'
    assert results[0].values['homo'] == -8
    assert results[1].error and results[1].values == {}
    assert len(json.loads((tmp_path/'out/predictions.json').read_text())['predictions']) == 3


def test_orca_uses_supplied_geometry_no_xtb(tmp_path, monkeypatch):
    xyz = tmp_path/'input.xyz'
    xyz.write_text(XYZ)
    monkeypatch.setattr(predictor, 'xtb_predict', lambda *a: pytest.fail('must not run xTB'))
    calls=[]
    def run(env, fallback, args, folder, log):
        calls.append(args)
        inp=(folder/'properties.inp').read_text()
        assert '! PBE0 def2-TZVP TightSCF' in inp and 'Dipole true' in inp
        assert (folder/'geometry.xyz').read_text()==XYZ
        log.write_text(ORCA)
    monkeypatch.setattr(predictor, 'run', run)
    result = predict_properties([molecule()], PredictorSettings(backend='orca', properties=['homo','dipole'],
        qm=QMSettings(functional='PBE0',basis='def2-TZVP')), tmp_path/'out',
        xyz_paths={'generated-1':xyz})[0]
    assert result.status is Status.ok and result.values=={'homo':-8.,'dipole':1.5}
    assert result.method=='dft:PBE0/def2-TZVP'
    assert result.metadata['qm_calls_attempted']==1 and len(calls)==1


def test_orca_force_field_geometry_has_no_xtb_call(tmp_path, monkeypatch):
    monkeypatch.setattr(predictor,'lowest_ff_conformer',lambda *a: (XYZ,{'selected_ff_boltzmann_weight':1.}))
    monkeypatch.setattr(predictor,'xtb_predict',lambda *a:pytest.fail('must not run xTB'))
    monkeypatch.setattr(predictor,'run',lambda env,b,args,folder,log:log.write_text(ORCA))
    result=predict_properties([molecule()],PredictorSettings(backend='orca',geometry='force_field'),tmp_path/'out')[0]
    assert result.status is Status.ok
    assert result.metadata['geometry_source']=='lowest_ff_only'


def test_orca_failure_attempt_is_retained(tmp_path, monkeypatch):
    xyz=tmp_path/'input.xyz'; xyz.write_text(XYZ)
    def fail(*a): raise RuntimeError('SCF process failed')
    monkeypatch.setattr(predictor,'run',fail)
    result=predict_properties([molecule()],PredictorSettings(backend='orca'),tmp_path/'out',
                             xyz_paths={'generated-1':xyz})[0]
    assert result.status is Status.failed and result.metadata['qm_calls_attempted']==1
    attempt=json.loads(Path(result.metadata['attempt_path']).read_text())
    assert attempt['status']=='failed'


def test_missing_property_retains_available_values(tmp_path, monkeypatch):
    xyz=tmp_path/'input.xyz'; xyz.write_text(XYZ)
    monkeypatch.setattr(predictor,'run',lambda env,b,args,folder,log:log.write_text(ORCA.split('DIPOLE MOMENT')[0]+'ORCA TERMINATED NORMALLY'))
    result=predict_properties([molecule()],PredictorSettings(backend='orca',properties=['homo','dipole']),
                             tmp_path/'out',xyz_paths={'generated-1':xyz})[0]
    assert result.status is Status.failed and result.values['homo']==-8.
    assert 'dipole' in result.errors
    assert result.as_prediction('homo').status is Status.ok
    assert result.as_prediction('dipole').status is Status.failed


def test_trained_ml_roundtrip_no_chemistry(tmp_path, monkeypatch):
    path=tmp_path/'model.json'; model=train(path)
    loaded=FingerprintModel.load(path)
    assert loaded.predict('CCO')==model.predict('CCO')
    monkeypatch.setattr(predictor,'xtb_predict',lambda *a:pytest.fail('ML must not run QM'))
    monkeypatch.setattr(predictor,'run',lambda *a:pytest.fail('ML must not run QM'))
    result=predict_properties([molecule(smiles='CCO')],PredictorSettings(backend='ml',model_path=path),tmp_path/'out')[0]
    assert result.status is Status.ok and result.xyz_path is None
    assert result.metadata['uncertainty']=='not_available'
    assert result.metadata['qm_calls_attempted']==0
    assert result.values['homo_lumo_gap']>0


def test_ml_contract_binding(tmp_path):
    path=tmp_path/'model.json';train(path)
    tool=PropertyPredictor(PredictorSettings(backend='ml',model_path=path))
    predictions=tool.predict([molecule(smiles='CCO')],PropertyTarget(name='homo_lumo_gap',max=8),tmp_path/'out')
    assert isinstance(predictions[0],Prediction) and predictions[0].candidate_id=='generated-1'
    assert predictions[0].status is Status.ok and predictions[0].xyz_path is None


def test_ml_missing_model_does_not_create_run(tmp_path):
    with pytest.raises(ValueError,match='model_path'):
        predict_properties([molecule()],PredictorSettings(backend='ml'),tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_invalid_model_and_training_labels(tmp_path):
    path=tmp_path/'bad.json';path.write_text('{"format":"unknown"}')
    with pytest.raises(ValueError): FingerprintModel.load(path)
    with pytest.raises(ValueError):
        train_fingerprint_model(['CCO','OCC'],{'homo_lumo_gap':[1,2]},reference_method='test')
    with pytest.raises(ValueError):
        train_fingerprint_model(['CCO','CC'],{'homo_lumo_gap':[1,float('nan')]},reference_method='test')


def test_invalid_input_and_duplicate_ids(tmp_path):
    with pytest.raises(ValueError,match='unique'):
        predict_properties([molecule(),molecule()],PredictorSettings(),tmp_path/'out')
    result=predict_properties([molecule(smiles='[NH4+]')],PredictorSettings(),tmp_path/'invalid')[0]
    assert result.status is Status.failed
    assert result.metadata['qm_calls_attempted']==0


def test_orca_rejects_wrong_geometry_composition(tmp_path, monkeypatch):
    xyz=tmp_path/'input.xyz';xyz.write_text('1\nHe\nHe 0 0 0\n')
    monkeypatch.setattr(predictor,'run',lambda *a:pytest.fail('must reject before QM'))
    result=predict_properties([molecule()],PredictorSettings(backend='orca'),tmp_path/'out',xyz_paths={'generated-1':xyz})[0]
    assert result.status is Status.failed and 'composition' in result.error


def test_cli_train_then_predict(tmp_path, monkeypatch):
    from molcurator_property_validation.__main__ import main
    labels=tmp_path/'labels.csv'
    labels.write_text('smiles,homo_lumo_gap,method\nCCO,5.0,reference\nCC,7.0,reference\nCCC,6.0,reference\nCO,5.5,reference\n')
    model=tmp_path/'model.json'
    monkeypatch.setattr('sys.argv',['molcurator-properties','train-ml','--input',str(labels),
                                   '--output',str(model),'--reference-method','reference'])
    assert main()==0
    molecules=tmp_path/'molecules.json'
    molecules.write_text('[{"id":"new-1","smiles":"CCN"}]')
    out=tmp_path/'prediction'
    monkeypatch.setattr('sys.argv',['molcurator-properties','predict','--backend','ml',
        '--model',str(model),'--input',str(molecules),'--output',str(out)])
    assert main()==0
    data=json.loads((out/'predictions.json').read_text())
    assert data['predictions'][0]['candidate_id']=='new-1'
    assert data['predictions'][0]['backend']=='ml'


def test_bound_tool_accepts_existing_xyz_dir_and_preserves_geometry(tmp_path, monkeypatch):
    def xtb(items,target,xyz_dir):
        folder=xyz_dir/'calculations'/items[0].id/'xtb';folder.mkdir(parents=True)
        (folder/'xtb.out').write_text(XTB)
        xyz=xyz_dir/f'{items[0].id}.xyz';xyz.write_text(XYZ)
        return [Prediction(candidate_id=items[0].id,status=Status.ok,value=5.,xyz_path=xyz)]
    monkeypatch.setattr(predictor,'xtb_predict',xtb)
    tool=PropertyPredictor(PredictorSettings(backend='xtb'))
    for _ in range(2):
        result=tool.predict([molecule()],PropertyTarget(name='homo_lumo_gap',max=10),tmp_path)[0]
        assert result.status is Status.ok
        assert result.xyz_path==tmp_path/'generated-1.xyz'
        assert result.xyz_path.read_text()==XYZ
