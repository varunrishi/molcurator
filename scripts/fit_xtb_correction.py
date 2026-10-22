"""Fit the on-top correction PREDICT applies to xTB gaps: DFT gap ~ slope * xTB gap + intercept.

Uses paired gaps already calculated for the same molecules (by default the 60 xTB / ORCA B3LYP/def2-SVP
pairs in data/properties/, the method in configs/homo_lumo.yaml). Prints the fit, how much it reduces
the error, and a `correction:` block to paste under `predict:` in a run config.

    python scripts/fit_xtb_correction.py [--dataset b3lyp_validation60]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "properties" / "molcurator_properties_for_collaborators.csv"


def fit(xtb: np.ndarray, dft: np.ndarray) -> dict:
    """Least-squares line from xTB to DFT gaps, its residual SD and the xTB range it covers."""
    slope, intercept = np.polyfit(xtb, dft, 1)
    residuals = dft - (slope * xtb + intercept)
    return {"slope": round(float(slope), 4), "intercept": round(float(intercept), 4),
            "residual_sd": round(float(residuals.std(ddof=2)), 3),  # two fitted parameters
            "xtb_range": [round(float(xtb.min()), 2), round(float(xtb.max()), 2)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATA, help="CSV with xtb_gap_ev and orca_gap_ev columns")
    parser.add_argument("--dataset", default="b3lyp_validation60",
                        help="rows of one method only: different DFT methods must not be mixed (PROPERTY_DATA.md)")
    args = parser.parse_args(argv)
    rows = pd.read_csv(args.data)
    rows = rows[(rows["dataset"] == args.dataset) & rows["xtb_gap_ev"].notna() & rows["orca_gap_ev"].notna()]
    if len(rows) < 3:
        raise SystemExit(f"need at least 3 paired gaps in dataset {args.dataset!r}, found {len(rows)}")
    xtb, dft = rows["xtb_gap_ev"].to_numpy(), rows["orca_gap_ev"].to_numpy()
    c = fit(xtb, dft)
    method = rows["reference_method"].dropna().iloc[0] if rows["reference_method"].notna().any() else args.dataset
    mae = lambda pred: float(np.abs(dft - pred).mean())  # noqa: E731
    print(f"{len(rows)} paired gaps ({args.dataset}, {method}); xTB {c['xtb_range'][0]}-{c['xtb_range'][1]} eV, "
          f"DFT {dft.min():.2f}-{dft.max():.2f} eV, r = {np.corrcoef(xtb, dft)[0, 1]:.2f}")
    print(f"DFT ~ {c['slope']} * xTB + {c['intercept']} eV; residual SD {c['residual_sd']} eV")
    print(f"mean absolute error vs DFT: raw xTB {mae(xtb):.2f} eV -> corrected {mae(c['slope'] * xtb + c['intercept']):.2f} eV")
    print("\nPaste under `predict:` in the run config:\n")
    print(f"  correction:  # on-top correction of xTB gaps to {method} (scripts/fit_xtb_correction.py)")
    print(f"    slope: {c['slope']}\n    intercept: {c['intercept']}\n    residual_sd: {c['residual_sd']}")
    print(f"    xtb_range: {c['xtb_range']}  # fitted xTB gaps; outside this the correction extrapolates")
    print(f"    fitted_on: \"{len(rows)} xTB/{method} pairs, {args.dataset}\"")


if __name__ == "__main__":
    main()
