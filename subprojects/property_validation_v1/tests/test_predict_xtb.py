import importlib
import json
from pathlib import Path
import shutil
import pytest
from molcurator.schemas import Candidate, PropertyTarget, Status
from molcurator_property_validation.chem.geometry import lowest_ff_conformer, xyz_symbols

module=importlib.import_module("molcurator_property_validation.tools.predict")
TARGET=PropertyTarget(name="homo_lumo_gap",min=3,max=4)
XYZ="2\nfixture\nH 0 0 0\nH 0 0 .74\n"
LOG="GEOMETRY OPTIMIZATION CONVERGED\nHOMO-LUMO GAP 3.25 eV\nnormal termination of xtb\n"
REPORT=dict(force_field="MMFF94",selected_ff_energy_kcal_mol=0.,selected_ff_boltzmann_weight=1.,temperature_k=298.15,n_unique=1)


def candidate(cid,smiles="CCO"):
    return Candidate(id=cid,smiles=smiles,parent_smiles="CCO",round=1,generator="test")


def test_mixed_results_preserve_ids_geometry_and_weight(tmp_path,monkeypatch):
    monkeypatch.setattr(module,"lowest_ff_conformer",lambda s:(XYZ,REPORT.copy()))
    calls=[]
    def run(env,b,args,folder,log):
        calls.append(folder.parent.name)
        if folder.parent.name=="bad":raise RuntimeError("xTB failed")
        log.write_text(LOG)
        shutil.copyfile(folder/"initial.xyz",folder/"xtbopt.xyz")
    monkeypatch.setattr(module,"run",run)
    results=module.predict([candidate("good"),candidate("bad"),candidate("last")],TARGET,tmp_path)
    assert [r.candidate_id for r in results]==["good","bad","last"]
    assert [r.status for r in results]==[Status.ok,Status.failed,Status.ok]
    assert results[0].value==3.25 and results[0].xyz_path.read_text()==XYZ
    assert results[1].value is None and results[1].error
    report=json.loads((tmp_path/"calculations/good/xtb/geometry_report.json").read_text())
    assert report["selected_ff_boltzmann_weight"]==1
    assert calls==["good","bad","last"]


def test_stale_geometry_is_not_accepted(tmp_path,monkeypatch):
    folder=tmp_path/"calculations/stale/xtb";folder.mkdir(parents=True)
    (folder/"xtbopt.xyz").write_text(XYZ)
    monkeypatch.setattr(module,"lowest_ff_conformer",lambda s:(XYZ,REPORT.copy()))
    monkeypatch.setattr(module,"run",lambda e,b,a,f,l:l.write_text(LOG))
    result=module.predict([candidate("stale")],TARGET,tmp_path)[0]
    assert result.status is Status.failed
    assert not (folder/"xtbopt.xyz").exists()


def test_real_rdkit_geometry(tmp_path):
    xyz,report=lowest_ff_conformer("CCCC",nconfs=8)
    path=tmp_path/"test.xyz";path.write_text(xyz)
    assert len(xyz_symbols(path))==14
    assert 0<report["selected_ff_boltzmann_weight"]<=1
    assert report["n_converged"]>=report["n_unique"]>=1


@pytest.mark.parametrize("smiles",["invalid","[NH4+]","[CH3]","C.C"])
def test_unsupported_chemistry(smiles):
    with pytest.raises(ValueError):lowest_ff_conformer(smiles)


def test_unsupported_target_has_failed_result(tmp_path):
    result=module.predict([candidate("x")],PropertyTarget(name="s1_t1_gap",max=.2),tmp_path)[0]
    assert result.status is Status.failed
