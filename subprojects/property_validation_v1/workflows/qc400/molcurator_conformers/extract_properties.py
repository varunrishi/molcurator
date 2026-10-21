#!/usr/bin/env python3
"""Extract final GFN2-xTB and ORCA 6.x properties into a one-row CSV.
Usage: python extract_properties.py --xtb xtb.out --orca excited.out --smiles c1ccncc1 --id pyridine --out pyridine.csv
No third-party dependencies.
"""
import argparse
import csv
import re
from pathlib import Path

NUMBER = r'[-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?'

def num(s):
    return float(s.replace('D', 'E').replace('d', 'e'))

def final_match(pattern, text, flags=re.I | re.M):
    matches = list(re.finditer(pattern, text, flags))
    return matches[-1] if matches else None

def parse_xtb(text):
    result = {'xtb_success': bool(re.search(r'normal termination of xtb', text, re.I))}
    m = final_match(r'(?:TOTAL ENERGY|::\s*total energy)\s+('+NUMBER+r')\s*Eh', text)
    if m: result['xtb_energy_eh'] = num(m.group(1))
    m = final_match(r'HOMO-LUMO (?:GAP|gap)\s+('+NUMBER+r')\s*eV', text)
    if m: result['xtb_gap_ev'] = num(m.group(1))
    for kind in ('HOMO', 'LUMO'):
        m = final_match(r'^\s*\d+\s+(?:2\.0000\s+)?'+NUMBER+r'\s+('+NUMBER+r')\s*\('+kind+r'\)', text)
        if m: result['xtb_'+kind.lower()+'_ev'] = num(m.group(1))
    m = final_match(r'^\s*full:\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s*$', text)
    if m: result['xtb_dipole_debye'] = num(m.group(4))
    return result

def parse_orca(text):
    result = {'orca_success': 'ORCA TERMINATED NORMALLY' in text}
    m = final_match(r'FINAL SINGLE POINT ENERGY\s+('+NUMBER+r')', text)
    if m: result['orca_energy_eh'] = num(m.group(1))
    # ORCA emits many orbital tables; use the last full occupied/unoccupied table.
    sections = re.split(r'^\s*ORBITAL ENERGIES\s*$', text, flags=re.M)
    for section in reversed(sections[1:]):
        occupied, virtual = [], []
        for line in section.splitlines():
            m = re.match(r'^\s*\d+\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s*$', line)
            if m:
                occ, ev = num(m.group(1)), num(m.group(3))
                if occ > 0.5: occupied.append(ev)
                else: virtual.append(ev)
            elif occupied and virtual:
                break
        if occupied and virtual:
            result['orca_homo_ev'] = occupied[-1]
            result['orca_lumo_ev'] = virtual[0]
            result['orca_gap_ev'] = virtual[0] - occupied[-1]
            break
    m = final_match(r'^\s*Magnitude \(Debye\)\s*:\s*('+NUMBER+r')', text)
    if m: result['orca_dipole_debye'] = num(m.group(1))
    # Match the electric-dipole LENGTH (D2) absorption table, not the velocity/P2 table.
    marker = 'ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS'
    if marker in text:
        sect = text.split(marker)[-1].split('ABSORPTION SPECTRUM VIA TRANSITION VELOCITY')[0]
        for line in sect.splitlines():
            m = re.match(r'^\s*0-\S+\s+->\s+(\d+)-\S+\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')', line)
            if m:
                i = int(m.group(1))
                result[f's{i}_ev'] = num(m.group(2))
                result[f's{i}_oscillator_strength'] = num(m.group(5))
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--xtb', required=True)
    p.add_argument('--orca', required=True)
    p.add_argument('--smiles', default='')
    p.add_argument('--id', default='')
    p.add_argument('--out', default='properties.csv')
    a=p.parse_args()
    row={'molecule_id':a.id,'smiles':a.smiles}
    row.update(parse_xtb(Path(a.xtb).read_text(errors='replace')))
    row.update(parse_orca(Path(a.orca).read_text(errors='replace')))
    keys = ['molecule_id','smiles','xtb_success','orca_success','xtb_energy_eh','orca_energy_eh','xtb_homo_ev','xtb_lumo_ev','xtb_gap_ev','xtb_dipole_debye','orca_homo_ev','orca_lumo_ev','orca_gap_ev','orca_dipole_debye']
    keys += [k for i in range(1,6) for k in (f's{i}_ev',f's{i}_oscillator_strength')]
    with open(a.out,'w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); writer.writeheader();writer.writerow(row)
    for k,v in row.items(): print(f'{k}: {v}')
    print('Wrote', a.out)
if __name__=='__main__': main()
