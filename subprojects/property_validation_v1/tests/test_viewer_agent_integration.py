import json
from pathlib import Path
from molcurator_property_validation.visualization.integration import publish_prediction_viewers


def test_disabled_does_not_create_files(tmp_path, monkeypatch):
    monkeypatch.setenv('MOLCURATOR_VIEWERS','0')
    assert publish_prediction_viewers([],tmp_path) is None
    assert not (tmp_path/'viewers').exists()


def test_index_preserves_failed_records(tmp_path, monkeypatch):
    monkeypatch.setenv('MOLCURATOR_VIEWERS','1')
    monkeypatch.setenv('MOLCURATOR_MAX_VIEWERS','0')
    data=[{'candidate_id':'a', 'status':'failed', 'error':'bad SMILES', 'value':None},
          {'candidate_id':'b', 'status':'ok', 'value':1.5, 'xyz_path':str(tmp_path/'none.xyz')}]
    result=publish_prediction_viewers(data,tmp_path)
    assert result['total']==2 and result['viewers_generated']==0
    records=json.loads((tmp_path/'viewers/index.json').read_text())['records']
    assert [r['candidate_id'] for r in records] == ['a','b']


def test_optional_failure_never_breaks_predictions(tmp_path, monkeypatch):
    monkeypatch.setenv('MOLCURATOR_VIEWERS','1')
    monkeypatch.setenv('MOLCURATOR_MAX_VIEWERS','invalid')
    assert publish_prediction_viewers([],tmp_path) is None
