"""Synthetic dataset contract tests; no cluster executables needed."""
import importlib.util
import pandas as pd
import pytest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/export_calibrated_properties.py'
spec=importlib.util.spec_from_file_location('export_properties_script',SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_export_success_and_failure(tmp_path):
    inp=tmp_path/'in.csv'; out=tmp_path/'out.csv'
    pd.DataFrame([{'candidate_id':'a','smiles':'CCO','status':'ok','xtb_gap_ev':1.,'orca_gap_ev':3.4,'method':'dft:B3LYP/def2-SVP','selection_probability':.5},
                  {'candidate_id':'b','smiles':'C','status':'failed','xtb_gap_ev':None,'orca_gap_ev':None,'method':'dft:B3LYP/def2-SVP','error':'timeout'}]).to_csv(inp,index=False)
    summary=module.export(inp,out)
    df=pd.read_csv(out)
    assert summary['n_qm_success']==1 and summary['n_true_hits']==1
    assert df.loc[0,'linear_predicted_gap_ev']==pytest.approx(module.SLOPE+module.INTERCEPT)
    assert pd.isna(df.loc[1,'linear_predicted_gap_ev'])
    assert 'ff_boltzmann_weight' in df
    assert out.with_suffix('.metadata.json').exists()

def test_reject_mismatched_method(tmp_path):
    inp=tmp_path/'in.csv'
    pd.DataFrame([{'candidate_id':'a','smiles':'C','status':'ok','xtb_gap_ev':1.,'orca_gap_ev':4.,'method':'dft:PBE0/def2-SVP'}]).to_csv(inp,index=False)
    with pytest.raises(ValueError,match='B3LYP'):
        module.export(inp,tmp_path/'out.csv')
