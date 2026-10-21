#!/usr/bin/env python3
"""Recover xTB/ORCA frontier orbitals and dipoles from MolCurator target-validation logs.

No quantum chemistry is run. Original export is never overwritten by default.
"""
import argparse
import math
import re
from pathlib import Path

import pandas as pd

NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
ORBITAL_ROW = re.compile(r"^\s*\d+\s+(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")\s*$")
XTB_FRONTIER = re.compile(r"^\s*\d+\s+(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")(?:\s+.*)?$")

def val(s):
    return float(s.replace('D', 'E').replace('d', 'e'))

def orca_frontier(text):
    if 'ORCA TERMINATED NORMALLY' not in text:
        return None, None
    segments = re.split(r'^\s*ORBITAL ENERGIES\s*$', text, flags=re.M)
    if len(segments) < 2:
        return None, None
    occupied, virtual = [], []
    active = False
    for line in segments[-1].splitlines():
        m = ORBITAL_ROW.fullmatch(line)
        if m:
            active = True
            occ, _, ev = map(val, m.groups())
            if math.isfinite(ev):
                if abs(occ - 2.0) < 1e-5: occupied.append(ev)
                elif abs(occ) < 1e-5: virtual.append(ev)
        elif active:
            break
    return (max(occupied) if occupied else None, min(virtual) if virtual else None)

def orca_dipole(text):
    sections = re.split(r'^\s*DIPOLE MOMENT\s*$', text, flags=re.M)
    for section in reversed(sections[1:]):
        match = re.search(r'^\s*Magnitude\s*\(Debye\)\s*:\s*(' + NUM + r')', section, re.M | re.I)
        if match: return val(match.group(1))
    return None

def xtb_dipole(text):
    # xTB versions may print rounded Cartesian components but a separate high-precision total.
    parts = re.split(r'^\s*molecular dipole:\s*$', text, flags=re.I | re.M)
    for part in reversed(parts[1:]):
        for line in part.splitlines()[:10]:
            m = re.match(r'^\s*full:\s*(' + NUM + r')\s+(' + NUM + r')\s+(' + NUM + r')\s+(' + NUM + r')\s*$', line, re.I)
            if m: return val(m.group(4))
    return None

def xtb_frontier(text):
    # xTB 6.x prints a separate orbital table in some verbosity modes. Only accept
    # unmistakable HOMO/LUMO marker lines, never derive absolute orbitals from the gap.
    homo = re.findall(r'^\s*\d+\s+' + NUM + r'\s+' + NUM + r'\s+(' + NUM + r')\s*\(HOMO\)\s*$', text, re.M | re.I)
    lumo = re.findall(r'^\s*\d+\s+' + NUM + r'\s+' + NUM + r'\s+(' + NUM + r')\s*\(LUMO\)\s*$', text, re.M | re.I)
    return (val(homo[-1]) if homo else None, val(lumo[-1]) if lumo else None)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True, help='Existing calibrated_properties.csv')
    p.add_argument('--root', type=Path, required=True, help='target_validation/screen directory')
    p.add_argument('--output', type=Path, required=True, help='New enriched CSV, distinct from input')
    a = p.parse_args()
    if a.input.resolve() == a.output.resolve(): p.error('Output must differ from input')
    df = pd.read_csv(a.input)
    if not {'candidate_id','orca_gap_ev','xtb_gap_ev'}.issubset(df.columns):
        p.error('Input missing candidate_id/orca_gap_ev/xtb_gap_ev')
    if df.candidate_id.duplicated().any(): p.error('Duplicate candidate IDs')
    errors=[]
    for idx, row in df.iterrows():
        cid = str(row.candidate_id)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', cid):
            errors.append(f'{cid}: invalid id'); continue
        folder = a.root / cid / 'xyz' / 'calculations' / cid
        xtbp, orcap = folder/'xtb'/'xtb.out', folder/'orca'/'orca.out'
        if not xtbp.exists() or not orcap.exists():
            errors.append(f'{cid}: missing {xtbp if not xtbp.exists() else orcap}'); continue
        xtb, orca = xtbp.read_text(errors='replace'), orcap.read_text(errors='replace')
        oh, ol = orca_frontier(orca)
        xh, xl = xtb_frontier(xtb)
        values = dict(orca_homo_ev=oh, orca_lumo_ev=ol,
                      orca_dipole_debye=orca_dipole(orca),
                      xtb_homo_ev=xh, xtb_lumo_ev=xl,
                      xtb_dipole_debye=xtb_dipole(xtb))
        for key, value in values.items():
            if value is not None and math.isfinite(value): df.at[idx, key] = value
        if oh is None or ol is None:
            errors.append(f'{cid}: ORCA orbital table not parsed')
        else:
            gap = ol - oh
            if pd.notna(row.orca_gap_ev) and abs(gap - float(row.orca_gap_ev)) > 0.002:
                errors.append(f'{cid}: ORCA gap mismatch: extracted {gap:.5f} vs saved {float(row.orca_gap_ev):.5f} eV')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.output, index=False)
    print('Saved:',a.output,'rows:',len(df))
    for col in ['xtb_homo_ev','xtb_lumo_ev','xtb_dipole_debye','orca_homo_ev','orca_lumo_ev','orca_dipole_debye']:
        print(f'{col:24s}: {df[col].notna().sum():3d}/{len(df)}')
    print('Warnings:',len(errors))
    for error in errors[:25]: print('WARNING',error)
    if len(errors)>25: print(f'... and {len(errors)-25} more')

if __name__ == '__main__': main()
