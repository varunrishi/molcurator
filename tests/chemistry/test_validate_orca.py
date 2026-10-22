import importlib,json
import pytest
from molcurator.schemas import Prediction, PropertyTarget, QMSettings, Status
from molcurator_property_validation.chem.calculations import orca_gap
module=importlib.import_module("molcurator_property_validation.tools.validate")
TARGET=PropertyTarget(name="homo_lumo_gap",min=3,max=4)
XYZ="2\nfixture\nH 0 0 0\nH 0 0 .74\n"
LOG="SCF CONVERGED AFTER 5 CYCLES\nORBITAL ENERGIES\n 0 2.0 -0.2 -5.0\n 1 0.0 -0.05 -1.5\n\nORCA TERMINATED NORMALLY\n"


def prediction(folder,cid):
    path=folder/f"{cid}.xyz";path.write_text(XYZ)
    return Prediction(candidate_id=cid,status=Status.ok,value=3.25,xyz_path=path)


def test_configured_method_mixed_failures_ids_and_attempts(tmp_path,monkeypatch):
    calls=[]
    def run(env,b,args,folder,log):
        calls.append(folder.parents[2].name)
        assert "PBE0 def2-TZVP" in (folder/"gap.inp").read_text()
        assert (folder/"geometry.xyz").read_text()==XYZ
        if folder.parents[2].name=="bad":
            (folder/"process.json").write_text(json.dumps(dict(process_started=True, electronic_calls_attempted=1)))
            raise RuntimeError("failed process")
        log.write_text(LOG)
    monkeypatch.setattr(module,"run",run)
    items=[prediction(tmp_path,"good"),prediction(tmp_path,"bad"),Prediction(candidate_id="prior-fail",status=Status.failed,error="xTB"),prediction(tmp_path,"last")]
    results=module.validate(items,TARGET,QMSettings(functional="PBE0",basis="def2-TZVP"))
    assert [r.candidate_id for r in results]==[p.candidate_id for p in items]
    assert [r.status for r in results]==[Status.ok,Status.failed,Status.failed,Status.ok]
    assert results[0].value==3.5
    assert all(r.method=="dft:PBE0/def2-TZVP" for r in results)
    assert calls==["good","bad","last"]
    attempt=json.loads((tmp_path/"calculations/bad/orca/attempt.json").read_text())
    assert attempt["qm_calls_attempted"]==1 and attempt["status"]=="failed"


@pytest.mark.parametrize("qm",[QMSettings(backend="pyscf"),QMSettings(functional="PBE0\n! Opt")])
def test_invalid_settings_never_launch(tmp_path,monkeypatch,qm):
    monkeypatch.setattr(module,"run",lambda *a:pytest.fail("must not launch"))
    assert module.validate([prediction(tmp_path,"x")],TARGET,qm)[0].status is Status.failed


@pytest.mark.parametrize("text",[LOG.replace("SCF CONVERGED AFTER","NOT CONVERGED"),LOG.replace("ORCA TERMINATED NORMALLY",""),LOG+"\nORBITAL ENERGIES\n 0 2.0 -0.2 -5.0\n"])
def test_reject_incomplete_or_unconverged_output(text):
    with pytest.raises(ValueError):orca_gap(text)


def test_final_table_wins():
    assert orca_gap(LOG.replace("-1.5","-2.5")+LOG)==3.5


def test_invalid_geometry_preserves_failure(tmp_path,monkeypatch):
    path=tmp_path/"bad.xyz";path.write_text("1\ninvalid\nH nan 0 0\n")
    monkeypatch.setattr(module,"run",lambda *a:pytest.fail("must not launch"))
    result=module.validate([Prediction(candidate_id="bad",status=Status.ok,value=3,xyz_path=path)],TARGET,QMSettings())[0]
    assert result.status is Status.failed and result.value is None
