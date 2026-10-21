from pathlib import Path
import argparse,json,csv,collections
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
manifest=a.root/'molecules.csv';n=sum(1 for _ in csv.DictReader(manifest.open())) if manifest.exists() else 0
files=list((a.root/'conformer_runs').glob('*/summary.json'));c=collections.Counter();orca=0
for f in files:
    try:
        x=json.loads(f.read_text());c[x.get('status','unknown')]+=1;orca+=int(x.get('n_orca_success') or 0)
    except (ValueError,OSError):c['unreadable']+=1
print(f'Manifest: {n} | summaries: {len(files)} | total successful ORCA: {orca} | statuses: {dict(c)}')
