"""Verify the actual public imports used by the main agent."""
import importlib
import shutil
from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status

public_predict=importlib.import_module('molcurator.tools.predict')
public_validate=importlib.import_module('molcurator.tools.validate')
xtb=importlib.import_module('molcurator_property_validation.tools.predict')
orca=importlib.import_module('molcurator_property_validation.tools.validate')
TARGET=PropertyTarget(name='homo_lumo_gap',min=3,max=4)
XYZ='2\nfixture\nH 0 0 0\nH 0 0 .74\n'
REPORT=dict(force_field='MMFF94',selected_ff_energy_kcal_mol=0.,selected_ff_boltzmann_weight=1.,temperature_k=298.15,n_unique=1)


def test_public_predict_delegates(tmp_path,monkeypatch):
    items=[];expected=[]
    def call(candidates,target,folder):
        assert candidates is items and target is TARGET and folder is tmp_path
        return expected
    monkeypatch.setattr(xtb,'predict',call)
    assert public_predict.predict(items,TARGET,tmp_path) is expected


def test_public_validate_delegates(monkeypatch):
    items=[];qm=QMSettings();expected=[]
    def call(batch,target,settings):
        assert batch is items and target is TARGET and settings is qm
        return expected
    monkeypatch.setattr(orca,'validate',call)
    assert public_validate.validate(items,TARGET,qm) is expected


def test_public_workflow_preserves_ids_failures_and_geometry(tmp_path,monkeypatch):
    monkeypatch.setattr(xtb,'lowest_ff_conformer',lambda s:(XYZ,REPORT.copy()))
    def xtb_run(env,b,args,folder,log):
        if folder.parent.name=='bad':raise RuntimeError('xTB failed')
        log.write_text('GEOMETRY OPTIMIZATION CONVERGED\nHOMO-LUMO GAP 3.25 eV\nnormal termination of xtb\n')
        assert '--opt' not in args
    def orca_run(env,b,args,folder,log):
        assert 'PBE0 def2-TZVP' in (folder/'gap.inp').read_text()
        assert (folder/'geometry.xyz').read_text()==XYZ
        log.write_text('SCF CONVERGED AFTER 5 CYCLES\nORBITAL ENERGIES\n 0 2.0 -.2 -5.0\n 1 0.0 -.05 -1.5\n\nORCA TERMINATED NORMALLY\n')
    monkeypatch.setattr(xtb,'run',xtb_run)
    monkeypatch.setattr(orca,'run',orca_run)
    candidates=[Candidate(id=i,smiles='CCO',parent_smiles='CCO',round=1,generator='test') for i in ('good','bad')]
    predictions=public_predict.predict(candidates,TARGET,tmp_path/'xyz')
    assert [p.candidate_id for p in predictions]==['good','bad']
    assert [p.status for p in predictions]==[Status.ok,Status.failed]
    results=public_validate.validate(predictions,TARGET,QMSettings(functional='PBE0',basis='def2-TZVP'))
    assert [r.candidate_id for r in results]==['good','bad']
    assert [r.status for r in results]==[Status.ok,Status.failed]
    assert results[0].value==3.5 and results[0].method=='dft:PBE0/def2-TZVP'
