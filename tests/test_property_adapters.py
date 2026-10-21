"""Offline contract tests: real FF sampling, simulated external program outputs."""
import importlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from rdkit import Chem

from molcurator.chem import calculations, geometry
from molcurator.schemas import Candidate, Prediction, PropertyTarget, QMSettings, Status

predict_module = importlib.import_module('molcurator.tools.predict')
validate_module = importlib.import_module('molcurator.tools.validate')
TARGET = PropertyTarget(name='homo_lumo_gap', min=3, max=4)
XYZ = '2\nfixture\nH 0 0 0\nH 0 0 0.74\n'
XTB = 'GEOMETRY OPTIMIZATION CONVERGED\nHOMO-LUMO GAP 3.25 eV\nnormal termination of xtb\n'
ORCA = '''SCF CONVERGED AFTER 8 CYCLES
ORBITAL ENERGIES
 NO OCC E(Eh) E(eV)
 0 2.0000 -0.3000 -8.0
 1 2.0000 -0.2000 -5.0
 2 0.0000 -0.0500 -1.5

ORCA TERMINATED NORMALLY
'''


def candidate(cid, smiles='CCO'):
    return Candidate(id=cid, smiles=smiles, parent_smiles='CCO', round=1, generator='fixture')


def prediction(tmp_path, cid):
    path = tmp_path / f'{cid}.xyz'
    path.write_text(XYZ)
    return Prediction(candidate_id=cid, status=Status.ok, value=3.25, xyz_path=path)


def test_lowest_ff_selection_and_boltzmann(monkeypatch):
    def optimize(mol, **kwargs):
        # Two carbon conformers always cluster together; assign distinct artificial
        # energies to verify selection is by energy rather than embedding order.
        return [(0, float(5 - i)) for i in range(mol.GetNumConformers())]
    monkeypatch.setattr(geometry.AllChem, 'MMFFOptimizeMoleculeConfs', optimize)
    xyz, report = geometry.lowest_ff_conformer('C', nconfs=3)
    assert report['selected_conformer_id'] == 2
    assert report['selected_ff_energy_kcal_mol'] == 3
    assert report['n_unique'] == 1
    assert report['selected_ff_boltzmann_weight'] == 1
    assert int(xyz.splitlines()[0]) == 5


def test_real_force_field_geometry(tmp_path):
    xyz, report = geometry.lowest_ff_conformer('CCCC', nconfs=8)
    path = tmp_path / 'real.xyz'
    path.write_text(xyz)
    assert len(geometry.xyz_symbols(path)) == Chem.AddHs(Chem.MolFromSmiles('CCCC')).GetNumAtoms()
    assert report['force_field'] == 'MMFF94'
    assert 0 < report['selected_ff_boltzmann_weight'] <= 1
    assert report['n_embedded'] == 8
    assert report['n_converged'] >= report['n_unique'] >= 1


def test_boltzmann_two_unique_minima(monkeypatch):
    monkeypatch.setattr(geometry.AllChem, 'MMFFOptimizeMoleculeConfs',
                        lambda mol, **kw: [(0, 0.0), (0, 1.0), (1, -100.0)])
    monkeypatch.setattr(geometry.rdMolAlign, 'GetBestRMS', lambda *args, **kw: 1.0)
    _, report = geometry.lowest_ff_conformer('CCO', nconfs=3)
    expected = 1 / (1 + math.exp(-1 / (0.00198720425864083 * 298.15)))
    assert report['selected_ff_boltzmann_weight'] == pytest.approx(expected)
    assert report['n_converged'] == 2


@pytest.mark.parametrize('smiles', ['invalid', '[NH4+]', '[CH3]', 'C.C'])
def test_unsupported_molecule(smiles):
    with pytest.raises(ValueError):
        geometry.lowest_ff_conformer(smiles)


def test_predict_mixed_results_and_geometry_handoff(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(predict_module, 'lowest_ff_conformer', lambda s: (XYZ, {'temperature_k': 298.15, 'force_field': 'MMFF94', 'selected_ff_energy_kcal_mol': 0.0, 'selected_ff_boltzmann_weight': 1.0, 'n_unique': 1}))
    def run(env, binary, args, folder, log):
        calls.append(folder.parent.name)
        log.write_text(XTB)
        if folder.parent.name == 'bad':
            raise subprocess.TimeoutExpired(binary, 1)
        shutil.copyfile(folder / 'initial.xyz', folder / 'xtbopt.xyz')
    monkeypatch.setattr(predict_module, 'run', run)
    results = predict_module.predict([candidate('good'), candidate('bad'), candidate('last')], TARGET, tmp_path)
    assert [r.candidate_id for r in results] == ['good', 'bad', 'last']
    assert [r.status for r in results] == [Status.ok, Status.failed, Status.ok]
    assert results[1].value is None and 'TimeoutExpired' in results[1].error
    assert results[0].xyz_path.read_text() == XYZ
    report = json.loads((tmp_path / 'calculations/good/xtb/geometry_report.json').read_text())
    assert report['candidate_id'] == 'good'
    assert calls == ['good', 'bad', 'last']


def test_predict_rejects_stale_geometry(tmp_path, monkeypatch):
    folder = tmp_path / 'calculations/stale/xtb'
    folder.mkdir(parents=True)
    (folder / 'xtbopt.xyz').write_text(XYZ)
    monkeypatch.setattr(predict_module, 'lowest_ff_conformer', lambda s: (XYZ, {'temperature_k': 298.15, 'force_field': 'MMFF94', 'selected_ff_energy_kcal_mol': 0.0, 'selected_ff_boltzmann_weight': 1.0, 'n_unique': 1}))
    monkeypatch.setattr(predict_module, 'run', lambda env, binary, args, folder, log: log.write_text(XTB))
    result = predict_module.predict([candidate('stale')], TARGET, tmp_path)[0]
    assert result.status is Status.failed
    assert not (folder / 'xtbopt.xyz').exists()


def test_validate_config_ids_failures_and_attempts(tmp_path, monkeypatch):
    calls = []
    def run(env, binary, args, folder, log):
        calls.append(folder.parent.name)
        assert (folder / 'geometry.xyz').read_text() == XYZ
        content = (folder / 'gap.inp').read_text()
        assert '! PBE0 def2-TZVP TightSCF' in content
        assert 'TDA' not in content
        if folder.parent.name == 'bad':
            raise RuntimeError('failed QC process')
        log.write_text(ORCA)
    monkeypatch.setattr(validate_module, 'run', run)
    items = [prediction(tmp_path, 'good'), prediction(tmp_path, 'bad'),
             Prediction(candidate_id='already-failed', status=Status.failed, error='embedding'),
             prediction(tmp_path, 'last')]
    results = validate_module.validate(items, TARGET, QMSettings(functional='PBE0', basis='def2-TZVP'))
    assert [r.candidate_id for r in results] == [r.candidate_id for r in items]
    assert [r.status for r in results] == [Status.ok, Status.failed, Status.failed, Status.ok]
    assert results[0].value == pytest.approx(3.5)
    assert all(r.method == 'dft:PBE0/def2-TZVP' for r in results)
    assert calls == ['good', 'bad', 'last']
    failed = json.loads((tmp_path / 'calculations/bad/orca/attempt.json').read_text())
    assert failed['status'] == 'failed' and failed['qm_calls_attempted'] == 1


@pytest.mark.parametrize('settings', [QMSettings(backend='pyscf'), QMSettings(functional='PBE0\n! Opt')])
def test_invalid_qm_settings_do_not_launch(tmp_path, monkeypatch, settings):
    monkeypatch.setattr(validate_module, 'run', lambda *a: pytest.fail('must not launch'))
    result = validate_module.validate([prediction(tmp_path, 'x')], TARGET, settings)[0]
    assert result.status is Status.failed


def test_unsupported_target_and_path_id(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_module, 'run', lambda *a: pytest.fail('must not launch'))
    unsupported = PropertyTarget(name='s1_t1_gap', max=0.2)
    assert predict_module.predict([candidate('x')], unsupported, tmp_path)[0].status is Status.failed
    assert predict_module.predict([candidate('../escape')], TARGET, tmp_path)[0].status is Status.failed


@pytest.mark.parametrize('text', [ORCA.replace('SCF CONVERGED AFTER', 'SCF NOT CONVERGED'),
                                 ORCA.replace('ORCA TERMINATED NORMALLY', ''),
                                 ORCA + '\nORBITAL ENERGIES\n 0 2.0 -0.2 -5.0\n'])
def test_orca_rejects_failed_or_incomplete_final_tables(text):
    with pytest.raises(ValueError):
        calculations.orca_gap(text)


def test_gap_parsers_use_final_values():
    assert calculations.xtb_gap(XTB.replace('3.25', '1.0') + XTB) == 3.25
    assert calculations.orca_gap(ORCA.replace('-1.5', '-2.5') + ORCA) == 3.5
    with pytest.raises(ValueError):
        calculations.xtb_gap(XTB.replace('GEOMETRY OPTIMIZATION CONVERGED', ''))


def test_runner_binary_timeout_and_exit(tmp_path, monkeypatch):
    monkeypatch.setenv('ORCA_BIN', 'configured-orca')
    monkeypatch.setenv('MOLCURATOR_QC_TIMEOUT_S', '17')
    monkeypatch.setattr(calculations.shutil, 'which', lambda name: str(tmp_path / name))
    def launch(args, **kwargs):
        assert args[0] == str((tmp_path / 'configured-orca').resolve())
        assert kwargs['timeout'] == 17
        assert kwargs['env']['OMP_NUM_THREADS'] == '1'
        return subprocess.CompletedProcess(args, 2)
    monkeypatch.setattr(calculations.subprocess, 'run', launch)
    with pytest.raises(RuntimeError, match='code 2'):
        calculations.run('ORCA_BIN', 'orca', ['gap.inp'], tmp_path, tmp_path / 'orca.out')


def test_uff_fallback_and_no_converged_ff(monkeypatch):
    monkeypatch.setattr(geometry.AllChem, 'MMFFHasAllMoleculeParams', lambda m: False)
    monkeypatch.setattr(geometry.AllChem, 'UFFOptimizeMoleculeConfs',
                        lambda m, **kw: [(0, 1.0)] * m.GetNumConformers())
    _, report = geometry.lowest_ff_conformer('CCO', nconfs=2)
    assert report['force_field'] == 'UFF'
    monkeypatch.setattr(geometry.AllChem, 'UFFOptimizeMoleculeConfs',
                        lambda m, **kw: [(1, 1.0)] * m.GetNumConformers())
    with pytest.raises(ValueError, match='no converged'):
        geometry.lowest_ff_conformer('CCO', nconfs=2)


def test_geometry_report_and_reject_changed_atoms(tmp_path, monkeypatch):
    report = dict(temperature_k=298.15, force_field='MMFF94', selected_ff_energy_kcal_mol=0,
                  selected_ff_boltzmann_weight=0.75, n_unique=2)
    monkeypatch.setattr(predict_module, 'lowest_ff_conformer', lambda s: (XYZ, report.copy()))
    def run(env, binary, args, folder, log):
        log.write_text(XTB)
        (folder / 'xtbopt.xyz').write_text(XYZ.replace('H 0 0 0.74', 'C 0 0 0.74'))
    monkeypatch.setattr(predict_module, 'run', run)
    old = tmp_path / 'changed.xyz'
    old.write_text(XYZ)
    result = predict_module.predict([candidate('changed')], TARGET, tmp_path)[0]
    assert result.status is Status.failed and 'atom identities' in result.error
    assert not old.exists()
    markdown = (tmp_path / 'calculations/changed/xtb/geometry_report.md').read_text()
    assert '75.00%' in markdown and '298.15' in markdown


def test_validation_missing_gap_fails_but_keeps_next(tmp_path, monkeypatch):
    def run(env, binary, args, folder, log):
        log.write_text(ORCA if folder.parent.name == 'good' else 'ORCA TERMINATED NORMALLY')
    monkeypatch.setattr(validate_module, 'run', run)
    results = validate_module.validate([prediction(tmp_path, 'missing'), prediction(tmp_path, 'good')],
                                       TARGET, QMSettings())
    assert [r.status for r in results] == [Status.failed, Status.ok]
    assert results[0].value is None


@pytest.mark.parametrize('text', ['1\ncomment\nH nan 0 0\n', '2\ncomment\nH 0 0 0\n'])
def test_invalid_xyz(tmp_path, text):
    path = tmp_path / 'broken.xyz'
    path.write_text(text)
    with pytest.raises(ValueError):
        geometry.xyz_symbols(path)


def test_missing_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(calculations.shutil, 'which', lambda name: None)
    with pytest.raises(FileNotFoundError):
        calculations.run('ORCA_BIN', 'orca', [], tmp_path, tmp_path / 'log')
