"""Check Python imports and chemistry executables; optional real one-molecule smoke test."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
# Also works before installation, so missing dependencies can be reported clearly.
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'subprojects/property_validation_v1/src'))
from molcurator_property_validation.chem.environment import load_binary_environment


def preflight(backend='all', env_file=None):
    load_binary_environment(env_file if env_file is not None else ROOT / '.env')
    checks = [dict(name='Python >= 3.11', ok=sys.version_info >= (3,11), detail=sys.version.split()[0])]
    for name in ('rdkit', 'pydantic', 'yaml', 'molcurator.tools.predict', 'molcurator.tools.validate',
                 'molcurator_property_validation.tools.predict', 'molcurator_property_validation.tools.validate'):
        try:
            module = importlib.import_module(name)
            checks.append(dict(name=name, ok=True, detail=str(getattr(module, '__version__', 'import OK'))))
        except Exception as exc:
            checks.append(dict(name=name, ok=False, detail=f'{type(exc).__name__}: {exc}'))
    for name in (('xtb', 'orca') if backend == 'all' else (backend,)):
        key = name.upper() + '_BIN'
        value = os.environ.get(key) or name
        executable = shutil.which(value)
        ok = bool(executable and Path(executable).is_file() and os.access(executable, os.X_OK))
        checks.append(dict(name=key, ok=ok,
            detail=f'{executable} (runtime not tested)' if ok else f'Not executable or not found: {value}. Set {key} to an absolute executable path or load its module.'))
    return dict(ok=all(c['ok'] for c in checks), backend=backend,
                checks=checks, runtime_tested=False)


def smoke(backend, output):
    from molcurator.schemas import Candidate, Prediction, PropertyTarget, QMSettings, Status
    from molcurator.tools.predict import predict
    from molcurator.tools.validate import validate
    from molcurator_property_validation.chem.geometry import lowest_ff_conformer
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    candidate = Candidate(id='ethanol', smiles='CCO', parent_smiles='CCO', round=1, generator='preflight')
    target = PropertyTarget(name='homo_lumo_gap', min=0)
    result = dict(backend=backend, predictions=[], qm_results=[], ok=False)
    if backend in ('xtb', 'all'):
        predictions = predict([candidate], target, output/'xyz')
        result['predictions'] = [p.model_dump(mode='json') for p in predictions]
    else:
        # ORCA-only preflight must not require xTB. Use an explicit FF geometry.
        xyz, metadata = lowest_ff_conformer(candidate.smiles)
        path = output/'ethanol-ff.xyz'; path.write_text(xyz)
        result['geometry_report'] = metadata
        predictions = [Prediction(candidate_id=candidate.id, status=Status.ok, value=0, xyz_path=path)]
        # The placeholder value only satisfies the legacy geometry-input contract;
        # it is not exposed as a calculated xTB observation.
        result['geometry_source'] = 'force_field_only'
    predicted = predictions[0].status is Status.ok
    (output/'preflight-smoke.json').write_text(json.dumps(result, indent=2))
    if backend in ('orca', 'all') and predicted:
        values = validate(predictions, target, QMSettings())
        result['qm_results'] = [r.model_dump(mode='json') for r in values]
        result['ok'] = values[0].status is Status.ok
    else:
        result['ok'] = predicted
    (output/'preflight-smoke.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('xtb','orca','all'), default='all')
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='run real chemistry on an allocated compute node')
    parser.add_argument('--out', type=Path, help='new smoke output directory')
    args = parser.parse_args()
    if args.smoke and args.out is None:
        parser.error('--smoke requires --out with a new directory')
    report = preflight(args.backend, args.env_file)
    if args.smoke and report['ok']:
        try:
            report['smoke'] = smoke(args.backend, args.out)
            report['runtime_tested'] = True
            report['ok'] = report['smoke']['ok']
        except Exception as exc:
            report.update(ok=False, smoke_error=f'{type(exc).__name__}: {exc}')
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for item in report['checks']:
            print(f"[{'OK' if item['ok'] else 'FAIL'}] {item['name']}: {item['detail']}")
        if args.smoke:
            print('Runtime smoke:', 'PASS' if report.get('smoke',{}).get('ok') else 'FAILED or not run')
        else:
            print('No chemistry was run. Use --smoke --out NEW_DIR on a compute node to test runtime.')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
