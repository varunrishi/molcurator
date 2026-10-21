"""Configured chemistry integration using the team's deterministic fake tool contract."""
import json
from pathlib import Path

import pytest

from molcurator.config import load_config
from molcurator.schemas import Candidate, Prediction, QMResult, Status
from molcurator.tools.chemistry import ChemistryTools, run_chemistry_round


@pytest.fixture
def config():
    return load_config(Path(__file__).resolve().parents[1] / 'configs/homo_lumo_calibrated.yaml')


def candidates():
    return [Candidate(id=name, smiles='CCO', parent_smiles='CCO', round=1,
                      generator='test') for name in ('near', 'outside', 'failed')]


def fake_tools():
    def predict(items, target, xyz_dir):
        xyz_dir.mkdir(parents=True)
        results = []
        for item in items:
            if item.id == 'failed':
                results.append(Prediction(candidate_id=item.id, status=Status.failed, error='xTB fail'))
                continue
            path = xyz_dir / f'{item.id}.xyz'
            path.write_text('2\nfixture\nH 0 0 0\nH 0 0 .74\n')
            results.append(Prediction(candidate_id=item.id, status=Status.ok,
                                      value=.4 if item.id == 'near' else 6., xyz_path=path))
        return results
    def validate(items, target, qm):
        return [QMResult(candidate_id=p.candidate_id, status=Status.ok, value=3.25,
                         method=f'dft:{qm.functional}/{qm.basis}') for p in items]
    return ChemistryTools(predict=predict, validate=validate)


def test_default_real_bindings():
    from molcurator.tools.predict import predict
    from molcurator.tools.validate import validate
    assert ChemistryTools().predict is predict
    assert ChemistryTools().validate is validate


def test_configured_stage_preserves_failures_and_reference_entries(tmp_path, config):
    result = run_chemistry_round(candidates(), config, tmp_path,
                                qm_calls_used=18, tools=fake_tools())
    assert result['qm_calls_charged'] == 2
    assert result['qm_batch_ids'] == ['near', 'outside']
    assert [p.candidate_id for p in result['predictions']] == ['near', 'outside', 'failed']
    assert result['predictions'][-1].error == 'xTB fail'
    assert result['curated_entries'][0].properties == {'xtb': .4, 'dft:B3LYP/def2-SVP': 3.25}
    report = json.loads(result['stage_path'].read_text())
    assert report['status'] == 'ok' and report['target_hits'] == 2
    assert report['exploration_ids'] == ['outside']
    assert report['config']['screening']['margin'] == .75
    assert report['candidates'][0]['parent_smiles'] == 'CCO'
    # Avoid silently repeating calculations on resume.
    with pytest.raises(FileExistsError):
        run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=18, tools=fake_tools())


def test_zero_budget_does_not_validate(tmp_path, config):
    tools = fake_tools()
    tools.validate = lambda *a: pytest.fail('zero budget must not invoke QM')
    result = run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=20, tools=tools)
    assert result['qm_calls_charged'] == 0 and result['qm_results'] == []


def test_agent_selector_gets_ranking_and_is_trimmed(tmp_path, config):
    def select(rows, remaining):
        assert rows[0]['raw_xtb_gap_ev'] == .4
        assert rows[-1]['status'] == 'failed'
        assert remaining == 1
        return ['outside', 'near']
    result = run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=19,
                                tools=fake_tools(), select_qm=select)
    assert result['qm_batch_ids'] == ['outside']
    assert json.loads(result['stage_path'].read_text())['trimmed_from'] == 2


@pytest.mark.parametrize('chosen', [['missing'], ['failed'], ['near', 'near']])
def test_bad_selection_never_launches_qm(tmp_path, config, chosen):
    tools = fake_tools()
    tools.validate = lambda *a: pytest.fail('invalid batch must not invoke QM')
    with pytest.raises(ValueError):
        run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=0,
                            tools=tools, select_qm=lambda *a: chosen)
    record = json.loads((tmp_path / 'chemistry/round-1/stage.json').read_text())
    assert record['status'] == 'failed' and record['qm_calls_charged'] == 0


def test_whole_qm_failure_persists_budget_reservation(tmp_path, config):
    tools = fake_tools()
    def crash(*a):
        raise RuntimeError('QM step crashed')
    tools.validate = crash
    with pytest.raises(RuntimeError):
        run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=19, tools=tools)
    record = json.loads((tmp_path / 'chemistry/round-1/stage.json').read_text())
    assert record['qm_calls_charged'] == 1 and record['status'] == 'failed'
    assert len(record['predictions']) == 3


def test_per_molecule_qm_failure_is_charged_not_curated(tmp_path, config):
    tools = fake_tools()
    tools.validate = lambda items, *a: [QMResult(candidate_id=p.candidate_id,
        status=Status.failed, error='SCF failed', method='dft:B3LYP/def2-SVP') for p in items]
    result = run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=18, tools=tools)
    assert result['qm_calls_charged'] == 2 and not result['curated_entries']


def test_wrong_tool_order_is_rejected(tmp_path, config):
    tools = fake_tools()
    original = tools.predict
    tools.predict = lambda *a: list(reversed(original(*a)))
    with pytest.raises(ValueError, match='ID/order'):
        run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=0, tools=tools)


def test_reference_value_controls_acceptance(tmp_path, config):
    tools = fake_tools()
    tools.validate = lambda items, *a: [QMResult(candidate_id=p.candidate_id,
        status=Status.ok, value=8., method='dft:B3LYP/def2-SVP') for p in items]
    result = run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=19, tools=tools)
    assert result['ranking'][0]['selected']
    assert result['curated_entries'] == []


def test_method_guard_before_calculations(tmp_path, config):
    config.qm.functional = 'PBE0'
    with pytest.raises(ValueError, match='B3LYP'):
        run_chemistry_round(candidates(), config, tmp_path, qm_calls_used=0)
    assert not (tmp_path / 'chemistry').exists()


def test_team_fake_tools_can_be_injected(tmp_path, config):
    from tests.agent.fakes import FakeTools
    fake = FakeTools(value_center=.4, value_spread=0, qm_offset=2.85, qm_noise=0)
    result = run_chemistry_round(candidates()[:1], config, tmp_path, qm_calls_used=0,
                                tools=ChemistryTools(predict=fake.predict, validate=fake.validate))
    assert len(result['curated_entries']) == 1
