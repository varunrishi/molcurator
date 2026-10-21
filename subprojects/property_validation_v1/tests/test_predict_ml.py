import json
import pytest
from molcurator.schemas import Candidate, PropertyTarget, Status
from molcurator_property_validation.ml import FingerprintModel, train_fingerprint_model
from molcurator_property_validation.tools.predict_ml import MLPredictor


def model():
    return train_fingerprint_model(["CCO","CC","CCC","CO"],
        {"homo_lumo_gap":[5.,7.,6.,5.5]},reference_method="dft:B3LYP/def2-SVP")


def candidate(cid,smiles):
    return Candidate(id=cid,smiles=smiles,parent_smiles="CCO",round=1,generator="test")


def test_model_save_load_roundtrip_and_metadata(tmp_path):
    path=tmp_path/"model.json";trained=model();trained.save(path)
    loaded=FingerprintModel.load(path)
    assert trained.predict("CCO")==loaded.predict("CCO")
    assert loaded.artifact["n_train"]==4
    assert loaded.artifact["uncertainty"]=="not_available"
    with pytest.raises(FileExistsError):trained.save(path)


def test_contract_ids_failures_and_no_geometry(tmp_path):
    path=tmp_path/"model.json";model().save(path)
    tool=MLPredictor(path)
    items=[candidate("good","CCO"),candidate("bad","invalid"),candidate("last","CCN")]
    results=tool.predict(items,PropertyTarget(name="homo_lumo_gap",max=10),tmp_path)
    assert [r.candidate_id for r in results]==[c.id for c in items]
    assert [r.status for r in results]==[Status.ok,Status.failed,Status.ok]
    assert all(r.xyz_path is None for r in results)
    record=json.loads(next((tmp_path/"ml_predictions").glob("*/predictions.json")).read_text())
    assert record["qm_calls_attempted"]==0 and record["uncertainty"]=="not_available"
    assert len(record["model_sha256"])==64


@pytest.mark.parametrize("target",[PropertyTarget(name="dipole",max=10,units="D"),PropertyTarget(name="homo_lumo_gap",max=10,units="Hartree")])
def test_missing_target_or_wrong_units_fail(tmp_path,target):
    path=tmp_path/"model.json";model().save(path)
    result=MLPredictor(path).predict([candidate("x","CCO")],target,tmp_path)[0]
    assert result.status is Status.failed and result.value is None


@pytest.mark.parametrize("smiles,labels",[(["CCO","OCC"],[1,2]),(["CCO","CC"],[1,float("nan")]),(["CCO","CC"],[1,-1])])
def test_bad_training_data(smiles,labels):
    with pytest.raises(ValueError):
        train_fingerprint_model(smiles,{"homo_lumo_gap":labels},reference_method="test")


def test_bad_artifact_rejected(tmp_path):
    path=tmp_path/"bad.json";path.write_text('{"format":"unknown"}')
    with pytest.raises(ValueError):MLPredictor(path)
