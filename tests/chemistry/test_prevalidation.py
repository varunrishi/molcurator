import importlib
import json
from pathlib import Path

import pytest

from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status
from molcurator.chem import geometry

predict_module = importlib.import_module("molcurator.tools.predict")
validate_module = importlib.import_module("molcurator.tools.validate")
TARGET = PropertyTarget(name="homo_lumo_gap", min=0)
XYZ = "2\ntest\nH 0 0 0\nH 0 0 .74\n"
REPORT = dict(force_field="MMFF94", selected_ff_energy_kcal_mol=0,
              selected_ff_boltzmann_weight=1, temperature_k=298.15, n_unique=1)


def candidate(smiles="CCO", cid="mol"):
    return Candidate(id=cid, smiles=smiles, parent_smiles=smiles, round=1, generator="test")


def record(root):
    return json.loads((root / "calculations/mol/xtb/prevalidation.json").read_text())


@pytest.fixture
def prohibit_backends(monkeypatch):
    def forbidden(*args):
        pytest.fail("invalid geometry must never reach an electronic backend")
    monkeypatch.setattr(predict_module, "run", forbidden)
    monkeypatch.setattr(validate_module, "run", forbidden)


def assert_stopped(tmp_path, code):
    prediction = predict_module.predict([candidate()], TARGET, tmp_path)[0]
    assert prediction.status is Status.failed and prediction.xyz_path is None
    event = record(tmp_path)
    assert event["code"] == code and event["status"] == "failed"
    assert not event["electronic_calls_allowed"] and event["electronic_calls_attempted"] == 0
    assert not (tmp_path / "mol.xyz").exists()
    assert not (tmp_path / "calculations/mol/xtb/initial.xyz").exists()
    assert not (tmp_path / "calculations/mol/xtb/attempts").exists()
    # Even a caller that forwards failures must not launch ORCA.
    qm = validate_module.validate([prediction], TARGET, QMSettings())[0]
    assert qm.status is Status.failed
    return prediction


def test_no_ensemble_or_single_geometry_stops_pipeline_and_removes_stale_xyz(tmp_path, monkeypatch, prohibit_backends):
    (tmp_path / "mol.xyz").write_text(XYZ)
    monkeypatch.setattr(geometry.AllChem, "EmbedMultipleConfs", lambda *a, **k: [])
    monkeypatch.setattr(geometry.AllChem, "EmbedMolecule", lambda *a, **k: -1)
    monkeypatch.setattr(geometry.AllChem, "MMFFHasAllMoleculeParams", lambda *a: pytest.fail("must stop before MMFF"))
    assert_stopped(tmp_path, "no_conformers")


def test_rdkit_embedding_exception_stops_pipeline(tmp_path, monkeypatch, prohibit_backends):
    def fail(*a, **k):
        raise RuntimeError("embedding failure fixture")
    monkeypatch.setattr(geometry.AllChem, "EmbedMultipleConfs", fail)
    assert_stopped(tmp_path, "embedding_failed")


@pytest.mark.parametrize("xyz,code", [(None, "missing_xyz"), ("", "missing_xyz"),
    ("2\ntest\nH nan 0 0\nH 0 0 .74\n", "invalid_xyz"),
    ("3\ntest\nH 0 0 0\nH 0 0 .74\n", "invalid_xyz")])
def test_missing_or_invalid_xyz_stops_before_xtb(tmp_path, monkeypatch, prohibit_backends, xyz, code):
    monkeypatch.setattr(predict_module, "lowest_ff_conformer", lambda *a: (xyz, REPORT.copy()))
    assert_stopped(tmp_path, code)


def test_xyz_file_creation_failure_stops_pipeline(tmp_path, monkeypatch, prohibit_backends):
    monkeypatch.setattr(predict_module, "lowest_ff_conformer", lambda *a: (XYZ, REPORT.copy()))
    original = Path.write_text
    def fail(path, *args, **kwargs):
        if path.name == "initial.xyz":
            raise OSError("XYZ write failure fixture")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail)
    assert_stopped(tmp_path, "xyz_write_failed")


def test_radical_and_charge_are_distinct_rdkit_rejections(tmp_path, prohibit_backends):
    for name, smiles, code, key in (("radical", "[CH3]", "unsupported_radical", "radical_electrons"),
                                    ("charge", "[NH4+]", "unsupported_charge", "formal_charge")):
        result = predict_module.predict([candidate(smiles, name)], TARGET, tmp_path)[0]
        assert result.status is Status.failed
        event = json.loads((tmp_path / f"calculations/{name}/xtb/prevalidation.json").read_text())
        assert event["code"] == code and event["details"][key] > 0


def test_failed_molecule_does_not_end_the_remaining_batch(tmp_path, monkeypatch):
    calls = []
    original = predict_module.lowest_ff_conformer
    def build(smiles):
        if smiles == "C":
            raise geometry.PreparationError("embedding", "no_conformers", "no embedded conformers")
        return original(smiles)
    monkeypatch.setattr(predict_module, "lowest_ff_conformer", build)
    def run(key, backend, args, folder, log):
        event = json.loads((folder.parents[1] / "prevalidation.json").read_text())
        assert event["status"] == "ok" and event["electronic_calls_allowed"]
        calls.append(event["candidate_id"])
        log.write_text("HOMO-LUMO GAP 3.25 eV\nnormal termination of xtb\n")
    monkeypatch.setattr(predict_module, "run", run)
    items = [candidate("C", "failed"), candidate("CCO", "good")]
    results = predict_module.predict(items, TARGET, tmp_path)
    assert [r.candidate_id for r in results] == ["failed", "good"]
    assert [r.status for r in results] == [Status.failed, Status.ok]
    assert calls == ["good"]


def test_no_converged_mmff_minima_stops_pipeline(tmp_path, monkeypatch, prohibit_backends):
    class Unconverged:
        def Minimize(self, **kwargs):
            return 1
        def CalcEnergy(self):
            return 0.0
    monkeypatch.setattr(geometry.AllChem, "MMFFGetMoleculeForceField", lambda *a, **k: Unconverged())
    assert_stopped(tmp_path, "no_converged_conformers")


def test_rdkit_xyz_export_exception_stops_pipeline(tmp_path, monkeypatch, prohibit_backends):
    def fail(*a, **k):
        raise RuntimeError("XYZ export failure fixture")
    monkeypatch.setattr(geometry.Chem, "MolToXYZBlock", fail)
    assert_stopped(tmp_path, "xyz_creation_failed")


def test_empty_ensemble_uses_single_geometry_and_optimizes(monkeypatch):
    monkeypatch.setattr(geometry.AllChem, "EmbedMultipleConfs", lambda *a, **k: [])
    xyz, report = geometry.lowest_ff_conformer("CCO")
    assert xyz.strip() and report["single_geometry_fallback"]
    assert report["geometry_source"] == "single_embedding_fallback"
    assert report["n_converged"] == report["n_unique"] == 1
    assert report["selected_ff_boltzmann_weight"] == 1


def test_empty_ensemble_reuses_existing_single_geometry(monkeypatch):
    embed = geometry.AllChem.EmbedMolecule
    def existing(mol, **kwargs):
        assert embed(mol, randomSeed=42) >= 0
        return []
    monkeypatch.setattr(geometry.AllChem, "EmbedMultipleConfs", existing)
    monkeypatch.setattr(geometry.AllChem, "EmbedMolecule", lambda *a, **k: pytest.fail("must reuse geometry"))
    xyz, report = geometry.lowest_ff_conformer("CCO")
    assert xyz.strip() and report["single_geometry_fallback"]
    assert report["geometry_source"] == "existing_single_geometry"
