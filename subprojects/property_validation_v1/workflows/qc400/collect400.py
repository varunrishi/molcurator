#!/usr/bin/env python3
import csv,json,argparse
from pathlib import Path
import pandas as pd
p=argparse.ArgumentParser();p.add_argument('--root',default='/work/AG_Presselt/MolCurator/qm9_400');a=p.parse_args();root=Path(a.root)
records=[];statuses=[]
for f in sorted((root/'conformer_runs').glob('*/summary.json')):
    d=json.loads(f.read_text());statuses.append({'molecule_id':f.parent.name,**d})
    csvfile=f.parent/'conformer_properties.csv'
    if not csvfile.exists():continue
    for r in csv.DictReader(csvfile.open()):
        if str(r.get('label_valid','')).lower()!='true':continue
        records.append(r)
if statuses:pd.DataFrame(statuses).to_csv(root/'workflow_status.csv',index=False)
if records:
    df=pd.DataFrame(records)
    for col in ('xtb_energy_eh','orca_energy_eh','xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye','orca_homo_ev','orca_lumo_ev','orca_gap_ev','orca_dipole_debye','s1_ev','xtb_relative_kcal'):
        if col in df:df[col]=pd.to_numeric(df[col],errors='coerce')
    df.to_csv(root/'all_valid_conformers.csv',index=False)
    # Representative label: minimum xTB electronic-energy ORCA-validated conformer
    main=df.sort_values('xtb_relative_kcal').drop_duplicates('molecule_id')
    main.to_csv(root/'representative_labels.csv',index=False)
    print('Molecules with valid ORCA labels:',len(main),'valid conformers:',len(df))
print('Workflow statuses:',pd.Series([r.get('status') for r in statuses]).value_counts().to_dict())
