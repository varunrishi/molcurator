from pathlib import Path
import argparse, os, importlib.util
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--source',required=True);a=p.parse_args()
for name,path in [('QM9 source',a.source),('data root',a.root),('xTB binary',os.getenv('XTB_BIN','')),('ORCA binary',os.getenv('ORCA_BIN',''))]:
    f=Path(path) if path else None; print(f'{name:12}: {path} ({"OK" if f and f.exists() else "MISSING"})')
for name in ('rdkit','numpy','pandas','sklearn','matplotlib','joblib'):
    print(f'{name:12}: {"OK" if importlib.util.find_spec(name) else "MISSING"}')
