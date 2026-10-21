#!/usr/bin/env python3
"""MolCurator 94 -> 276 ML benchmark with frozen 19-molecule test set."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
import joblib

FEATURES = ['xtb_homo_ev', 'xtb_lumo_ev', 'xtb_gap_ev', 'xtb_dipole_debye']
REQUIRED = ['molecule_id', 'smiles', 'xtb_success', 'orca_success', 's1_ev', 's1_oscillator_strength'] + FEATURES
MODEL_NAMES = ['mean', 'morgan_rf', 'xtb_rf', 'combined_rf', 'xtb_ridge']


def good_flag(series):
    return series.astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])


def make_model(name, seed):
    if name == 'xtb_ridge':
        return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge(alpha=1.0))
    return make_pipeline(SimpleImputer(strategy='median'), RandomForestRegressor(
        n_estimators=300, random_state=seed, min_samples_leaf=2, n_jobs=1))


def collect(roots, output):
    paths = sorted(f for root in roots for f in root.glob('*/properties.csv'))
    if not paths:
        raise SystemExit('No molecular properties.csv files found in the supplied roots')
    rows, errors = [], []
    for path in paths:
        try:
            frame = pd.read_csv(path)
            if len(frame) != 1:
                raise ValueError(f'Expected one row, got {len(frame)}')
            frame['source_file'] = str(path)
            rows.append(frame)
        except Exception as exc:
            errors.append({'path': str(path), 'reason': str(exc)})
    if not rows:
        raise SystemExit('No readable property files')
    data = pd.concat(rows, ignore_index=True)
    missing = sorted(set(REQUIRED) - set(data.columns))
    if missing:
        raise SystemExit(f'Missing required properties: {missing}')
    data.to_csv(output / 'all_parsed_rows.csv', index=False)
    data['duplicate_id'] = data.duplicated('molecule_id', keep=False)
    for col in ['s1_ev', 's1_oscillator_strength'] + FEATURES:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    mols = [Chem.MolFromSmiles(str(s)) for s in data['smiles']]
    data['canonical_smiles'] = [Chem.MolToSmiles(m, isomericSmiles=True) if m else '' for m in mols]
    data['qc_valid'] = (good_flag(data['xtb_success']) & good_flag(data['orca_success']) &
                        data['canonical_smiles'].ne('') &
                        data['s1_ev'].between(0.01, 20) &
                        data['s1_oscillator_strength'].ge(0) &
                        np.isfinite(data['s1_ev']) &
                        np.isfinite(data['s1_oscillator_strength']))
    # Missing xTB features are permissible for imputation but all four missing is not.
    data['qc_valid'] &= data[FEATURES].notna().any(axis=1)
    data.to_csv(output / 'curation_audit.csv', index=False)
    clean = data[data.qc_valid].copy().sort_values(['molecule_id', 'source_file'])
    clean = clean.drop_duplicates('molecule_id', keep='first')
    dup_structures = clean[clean.duplicated('canonical_smiles', keep=False)]
    dup_structures.to_csv(output / 'duplicate_structures.csv', index=False)
    clean = clean.drop_duplicates('canonical_smiles', keep='first').reset_index(drop=True)
    clean.to_csv(output / 'ml_dataset.csv', index=False)
    return clean, {'property_files': len(paths), 'read_errors': errors, 'unique_valid': len(clean),
                   'duplicated_structure_rows': len(dup_structures),
                   'method': 'GFN2-xTB geometry + TDA-PBE0/def2-SVP excited-state energy'}


def calc_metrics(y, predicted, model_name, train_size, dataset_name):
    return {'dataset': dataset_name, 'model': model_name, 'train_n': int(train_size), 'test_n': len(y),
            'mae_ev': float(mean_absolute_error(y, predicted)),
            'rmse_ev': float(np.sqrt(mean_squared_error(y, predicted))),
            'r2': float(r2_score(y, predicted))}


def run():
    p = argparse.ArgumentParser()
    p.add_argument('--root100', type=Path, default=Path('/work/AG_Presselt/MolCurator/qm9_100'))
    p.add_argument('--root200', type=Path, default=Path('/work/AG_Presselt/MolCurator/qm9_200'))
    p.add_argument('--baseline94', type=Path, default=None)
    p.add_argument('--output', type=Path, default=Path('/work/AG_Presselt/MolCurator/ml276'))
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    original_dir = (args.baseline94 or args.root100 / 'baseline94').resolve()
    frozen_file = original_dir / 'frozen_test_ids.csv'
    original_metrics = original_dir / 'model_metrics.csv'
    if not frozen_file.exists():
        raise SystemExit(f'Missing original frozen test IDs: {frozen_file}')
    if not original_metrics.exists():
        raise SystemExit(f'Missing original model metrics: {original_metrics}')
    original_ids = pd.read_csv(frozen_file).molecule_id.astype(str).tolist()
    if len(original_ids) != 19 or len(set(original_ids)) != len(original_ids):
        raise SystemExit('Expected 19 unique original frozen test IDs; verify before comparing')
    good, audit = collect([args.root100, args.root200], out)
    by_id = good.set_index('molecule_id', drop=False)
    missing_test = sorted(set(original_ids) - set(by_id.index))
    if missing_test:
        raise SystemExit(f'Frozen test IDs missing from expanded data: {missing_test}')
    # Exclude *all structures matching test molecule identities* from model training.
    test = by_id.loc[original_ids].copy()
    test_structures = set(test.canonical_smiles)
    train = good[~good.molecule_id.isin(original_ids) & ~good.canonical_smiles.isin(test_structures)].copy()
    if len(train) < 10:
        raise SystemExit('Insufficient training molecules')
    print(f'Validated molecules: {len(good)}; train: {len(train)}; frozen test: {len(test)}', flush=True)
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    def features(df):
        fps = []
        for smiles in df.canonical_smiles:
            fp = generator.GetFingerprint(Chem.MolFromSmiles(smiles))
            arr = np.zeros((1024,), dtype=np.int8)
            DataStructs.ConvertToNumpyArray(fp, arr)
            fps.append(arr)
        fingerprint = np.asarray(fps)
        xtb = df[FEATURES].to_numpy(float)
        return {'morgan_rf': fingerprint, 'xtb_rf': xtb,
                'combined_rf': np.column_stack((fingerprint, xtb)), 'xtb_ridge': xtb}
    x_train, x_test = features(train), features(test)
    y_train = train.s1_ev.to_numpy(float)
    y_test = test.s1_ev.to_numpy(float)
    predictions = test[['molecule_id', 'smiles', 's1_ev']].copy().reset_index(drop=True)
    metrics = []
    for name in MODEL_NAMES:
        if name == 'mean':
            pred = np.full(len(test), float(y_train.mean()))
        else:
            model = make_model(name, args.seed)
            model.fit(x_train[name], y_train)
            pred = model.predict(x_test[name])
            joblib.dump(model, out / f'{name}.joblib')
        predictions[f'{name}_pred_ev'] = pred
        metrics.append(calc_metrics(y_test, pred, name, len(train), 'expanded'))
        print(f'{name:12s} MAE={metrics[-1]["mae_ev"]:.4f} eV', flush=True)
    predictions.to_csv(out/'holdout_predictions_276.csv', index=False)
    expanded = pd.DataFrame(metrics)
    expanded.to_csv(out/'model_metrics_276.csv', index=False)
    original = pd.read_csv(original_metrics)
    original['dataset'] = 'original94'
    compare = pd.concat([original, expanded], ignore_index=True)
    compare.to_csv(out/'model_comparison_94_vs_276.csv', index=False)
    print('\nCOMPARISON ON ORIGINAL 19 MOLECULES:\n', compare[['dataset','model','train_n','test_n','mae_ev','rmse_ev','r2']].to_string(index=False))
    # Compare MAE by model.
    pivot = compare.pivot(index='model',columns='dataset',values='mae_ev').reindex(MODEL_NAMES)
    ax = pivot.plot(kind='bar', figsize=(9,5))
    ax.set_ylabel('Held-out S1 MAE (eV)');ax.set_xlabel('Model')
    ax.set_title('Same 19 frozen molecules: original vs expanded training')
    ax.tick_params(axis='x', rotation=25)
    ax.figure.tight_layout();ax.figure.savefig(out/'mae_comparison_94_vs_276.png', dpi=220);plt.close(ax.figure)
    # Prediction plots.
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.3), sharex=True,sharey=True)
    for ax, name in zip(axes, ['morgan_rf','xtb_rf','combined_rf']):
        ax.scatter(y_test, predictions[name+'_pred_ev'], alpha=.8)
        lo = min(y_test.min(), predictions[name+'_pred_ev'].min())
        hi = max(y_test.max(), predictions[name+'_pred_ev'].max())
        ax.plot([lo,hi],[lo,hi],'--',color='gray')
        ax.set_title(name)
        ax.set_xlabel('ORCA S1 (eV)')
    axes[0].set_ylabel('Predicted S1 (eV)')
    fig.tight_layout();fig.savefig(out/'predicted_vs_qc_276.png',dpi=220);plt.close(fig)
    # Learning curves: keep the frozen 19-molecule test set identical. Multiple resamples.
    sizes = sorted(set([s for s in [25, 50, 75, 100, 150, 200, len(train)] if s <= len(train)]))
    rng = np.random.default_rng(args.seed)
    lc=[]
    reps=4
    for n in sizes:
        for rep in range(reps):
            selected = rng.choice(len(train), size=n, replace=False)
            for name in ['morgan_rf','xtb_rf','combined_rf']:
                model = make_model(name, args.seed + rep)
                model.fit(x_train[name][selected], y_train[selected])
                pred = model.predict(x_test[name])
                lc.append({'model':name,'train_n':n,'repeat':rep,'mae_ev':mean_absolute_error(y_test,pred)})
        print(f'Learning curve {n}/{len(train)} training labels done',flush=True)
    learning = pd.DataFrame(lc)
    learning.to_csv(out/'learning_curve_repeats.csv',index=False)
    agg=learning.groupby(['model','train_n'])['mae_ev'].agg(['mean','std']).reset_index()
    agg.to_csv(out/'learning_curve_summary.csv',index=False)
    fig,ax=plt.subplots(figsize=(7.4,5.2))
    for name, grp in agg.groupby('model'):
        grp=grp.sort_values('train_n')
        ax.errorbar(grp.train_n,grp['mean'],yerr=grp['std'].fillna(0),marker='o',capsize=2,label=name)
    ax.set_xlabel('Number of training molecules');ax.set_ylabel('MAE on frozen 19-molecule test set (eV)')
    ax.set_title('Learning curve (4 random subsamples per size)');ax.legend()
    fig.tight_layout();fig.savefig(out/'learning_curve.png',dpi=220);plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4.5))
    ax.hist(good.s1_ev,bins=25);ax.set_xlabel('ORCA S1 excitation energy (eV)');ax.set_ylabel('Molecules')
    ax.set_title(f'Expanded dataset: {len(good)} validated molecules')
    fig.tight_layout();fig.savefig(out/'s1_hist_276.png',dpi=220);plt.close(fig)
    summary={'audit':audit,'train_n':len(train),'test_n':len(test),'test_ids':original_ids,
             'target':'vertical singlet excitation energy S0->S1 eV',
             'feature_sets':{'morgan_rf':'Morgan radius2 1024bit', 'xtb_rf':FEATURES,
                             'combined_rf':'Morgan + xTB', 'xtb_ridge':FEATURES},
             'caution':'Frozen test comparison uses one small 19-molecule test set; no scaffold split.'}
    (out/'experiment_summary.json').write_text(json.dumps(summary,indent=2))
    print('\nAll outputs:',out)

if __name__=='__main__':
    run()
