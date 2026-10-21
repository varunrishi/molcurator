"""Preflight reports availability without starting calculations."""
import importlib.util
import json
import os
from pathlib import Path

from molcurator_property_validation.chem.environment import load_binary_environment

spec=importlib.util.spec_from_file_location('check_property_tools',Path(__file__).resolve().parents[1]/'scripts/check_property_tools.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)


def test_environment_loads_only_binary_settings_and_keeps_overrides(tmp_path,monkeypatch):
    path=tmp_path/'.env'
    path.write_text('XTB_BIN="/from/file/xtb"\nORCA_BIN=/from/file/orca\nANTHROPIC_API_KEY=not-exported\nMOLCURATOR_QC_TIMEOUT_S=42\n')
    monkeypatch.setenv('XTB_BIN','/existing/xtb')
    monkeypatch.delenv('ORCA_BIN',raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    monkeypatch.delenv('MOLCURATOR_QC_TIMEOUT_S',raising=False)
    load_binary_environment(path)
    assert os.environ['XTB_BIN']=='/existing/xtb'
    assert os.environ['ORCA_BIN']=='/from/file/orca'
    assert os.environ['MOLCURATOR_QC_TIMEOUT_S']=='42'
    assert 'ANTHROPIC_API_KEY' not in os.environ


def test_paths_from_environment_are_checked_without_launch(tmp_path,monkeypatch):
    exe=tmp_path/'fake-program';exe.write_text('fixture');exe.chmod(0o755)
    monkeypatch.setenv('XTB_BIN',str(exe));monkeypatch.setenv('ORCA_BIN',str(exe))
    report=check.preflight('all',tmp_path/'absent.env')
    assert report['ok'] and not report['runtime_tested']
    assert len([c for c in report['checks'] if c['name'].endswith('_BIN')])==2


def test_missing_binary_fails_with_actionable_message(tmp_path,monkeypatch):
    monkeypatch.setenv('XTB_BIN',str(tmp_path/'missing'))
    report=check.preflight('xtb',tmp_path/'absent.env')
    assert not report['ok']
    assert 'Set XTB_BIN' in report['checks'][-1]['detail']


def test_cli_json_no_smoke_by_default(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(check,'preflight',lambda *a:dict(ok=True,checks=[],runtime_tested=False))
    monkeypatch.setattr(check,'smoke',lambda *a: (_ for _ in ()).throw(AssertionError('must not calculate')))
    monkeypatch.setattr('sys.argv',['check_property_tools.py','--json'])
    assert check.main()==0
    assert not json.loads(capsys.readouterr().out)['runtime_tested']


def test_runtime_smoke_failure_returns_nonzero(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(check,'preflight',lambda *a:dict(ok=True,checks=[],runtime_tested=False))
    monkeypatch.setattr(check,'smoke',lambda *a:dict(ok=False))
    monkeypatch.setattr('sys.argv',['check_property_tools.py','--json','--smoke','--out',str(tmp_path/'run')])
    assert check.main()==1
    report=json.loads(capsys.readouterr().out)
    assert report['runtime_tested'] and not report['ok']
