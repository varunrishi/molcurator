#!/usr/bin/env python3
"""Export validated HOMO–LUMO properties while preserving method and provenance.

Reads consolidated_validation.csv (60 stratified ORCA jobs) and optionally a
separate historical ml_dataset.csv (PBE0 dataset) for comparisons; NEVER silently
mixes differing DFT methods in one target/calibration analysis.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd

SLOPE = 0.8270780546046135
INTERCEPT = 2.9901896256531098
OFFSET = 2.2617441034023127
CAL_METHOD = 'dft:B3LYP/def2-SVP'
FIELDS = [
    'dataset','candidate_id','smiles','status','error','xtb_method','qm_method',
    'geometry_policy','xyz_path','xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev',
    'xtb_dipole_debye','orca_homo_ev','orca_lumo_ev','orca_gap_ev',
    'orca_dipole_debye','linear_predicted_gap_ev','offset_predicted_gap_ev',
    'linear_error_ev','offset_error_ev','true_hit','prediction_margin_ev',
    'within_margin','ff_method','ff_energy_kcal_mol','ff_boltzmann_weight',
    'temperature_k','n_unique_conformers','selection_probability',
    'inverse_probability_weight','stratum','qm_calls_attempted'
]

def export(validation: Path, output: Path, historical: Path | None = None,
           target_min: float = 3., target_max: float = 3.5,
           margin: float = .75, geometry_root: Path | None = None) -> dict:
    if target_min > target_max or margin < 0:
        raise ValueError('Invalid target bounds or margin')
    df = pd.read_csv(validation)
    required = {'candidate_id','smiles','xtb_gap_ev','orca_gap_ev','status','method'}
    missing = required - set(df)
    if missing: raise ValueError(f'Missing validation columns: {sorted(missing)}')
    if df['candidate_id'].isna().any() or df['candidate_id'].duplicated().any():
        raise ValueError('Candidate IDs missing or duplicated')
    if ((df['status'] == 'ok') & df[['xtb_gap_ev','orca_gap_ev']].isna().any(axis=1)).any():
        raise ValueError('Successful QC rows must contain both gaps')
    if ((df['status'] == 'ok') & (df['method'] != CAL_METHOD)).any():
        raise ValueError('Frozen calibration only supports ORCA B3LYP/def2-SVP')
    records = []
    for _, r in df.iterrows():
        ok = str(r['status']) == 'ok'
        raw = float(r['xtb_gap_ev']) if ok else None
        dft = float(r['orca_gap_ev']) if ok else None
        linear = SLOPE*raw + INTERCEPT if ok else None
        offset = raw + OFFSET if ok else None
        distance = max(target_min-linear, 0, linear-target_max) if ok else None
        info = {}
        if geometry_root is not None:
            report = geometry_root / str(r['candidate_id']) / 'xyz' / 'calculations' / str(r['candidate_id']) / 'xtb' / 'geometry_report.json'
            if report.exists(): info = json.loads(report.read_text())
        records.append({
            'dataset':'target_validation60','candidate_id':r['candidate_id'],
            'smiles':r['smiles'],'status':r['status'],
            'error':r.get('error'),'xtb_method':'GFN2-xTB',
            'qm_method':r['method'],'geometry_policy':'lowest_converged_FF_then_xTB',
            'xyz_path':r.get('xyz_path'),'xtb_gap_ev':raw,'orca_gap_ev':dft,
            'linear_predicted_gap_ev':linear,'offset_predicted_gap_ev':offset,
            'linear_error_ev':linear-dft if ok else None,
            'offset_error_ev':offset-dft if ok else None,
            'true_hit':target_min <= dft <= target_max if ok else None,
            'prediction_margin_ev':margin, 'within_margin':distance <= margin if ok else None,
            'ff_method':info.get('force_field'),
            'ff_energy_kcal_mol':info.get('selected_ff_energy_kcal_mol'),
            'ff_boltzmann_weight':info.get('selected_ff_boltzmann_weight'),
            'temperature_k':info.get('temperature_k'),
            'n_unique_conformers':info.get('n_unique'),
            'selection_probability':r.get('selection_probability'),
            'inverse_probability_weight':r.get('inverse_probability_weight'),
            'stratum':r.get('stratum'),
            'qm_calls_attempted':r.get('qm_calls_attempted'),
        })
    result = pd.DataFrame.from_records(records).reindex(columns=FIELDS)
    output.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(output,index=False)
    summary = {'source':str(validation),'output':str(output),'n_rows':len(result),
               'n_qm_success':int((result.status=='ok').sum()),
               'n_true_hits':int((result.true_hit==True).sum()),
               'method':CAL_METHOD,'calibration':'linear_24',
               'slope':SLOPE,'intercept_ev':INTERCEPT,'offset_ev':OFFSET,
               'target_min_ev':target_min,'target_max_ev':target_max,
               'provisional_margin_ev':margin,
               'note':'Calibrated estimates are research ranking aids, not validated hard-exclusion criteria. Optional unmeasured properties are blank.'}
    output.with_suffix('.metadata.json').write_text(json.dumps(summary,indent=2)+'\n')
    if historical is not None:
        h = pd.read_csv(historical)
        cols = ['molecule_id','smiles','xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye',
                'orca_homo_ev','orca_lumo_ev','orca_gap_ev','orca_dipole_debye','s1_ev','s1_oscillator_strength']
        if set(cols)-set(h): raise ValueError(f'Historical dataset missing columns: {sorted(set(cols)-set(h))}')
        sub = h.loc[:,cols].rename(columns={'molecule_id':'candidate_id'})
        sub.insert(0,'qm_method','dft:PBE0/def2-SVP')
        sub.insert(0,'dataset','historical_ml276')
        sub.to_csv(output.with_name('historical_ml276_properties.csv'),index=False)
        summary['historical_export'] = str(output.with_name('historical_ml276_properties.csv'))
        output.with_suffix('.metadata.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--validation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--historical',type=Path)
    p.add_argument('--geometry-root',type=Path)
    p.add_argument('--min',type=float,default=3.)
    p.add_argument('--max',type=float,default=3.5)
    p.add_argument('--margin',type=float,default=.75)
    a=p.parse_args()
    print(json.dumps(export(a.validation,a.output,a.historical,a.min,a.max,a.margin,a.geometry_root),indent=2))
if __name__=='__main__':main()
