"""molcurator-properties: predict (and optionally QM-validate) one property for a CSV or
SMILES file, write reports, or generate a SLURM script. Same tools as the agent's PREDICT
and VALIDATE steps."""
import argparse
import subprocess
import sys
from pathlib import Path

from molcurator.batch.inputs import read_candidates  # noqa: F401 - part of the command's API
from molcurator.batch.runtime import run_lock  # noqa: F401 - part of the command's API
from molcurator.fileio import native_path
from molcurator.tools.predict import (
    predict_with_method as predict,  # PREDICT with --predict-method
)
from molcurator.tools.validate import validate


def run_batch(args) -> int:
    from molcurator.batch.runner import run_batch as execute
    return execute(args, predict_fn=predict, validate_fn=validate)


def _plot_flags(parser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plots", action="store_true", help="write PNG plots (needs matplotlib)")
    group.add_argument("--no-plots", dest="plots", action="store_false", help="no plots (default)")
    parser.set_defaults(plots=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="molcurator-properties", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="predict a CSV or SMILES file and write reports")
    run.add_argument("input", type=Path)
    run.add_argument("--format", choices=("auto", "csv", "smi"), default="auto")
    run.add_argument("--out", type=Path, required=True, help="new output directory (existing with --resume)")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--property", default="homo_lumo_gap", help="target property (default homo_lumo_gap)")
    run.add_argument("--units", help="unit of --min/--max; default: the property's own (checked)")
    run.add_argument("--predict-method", help="PREDICT method; default GFN2-xTB, or B97-3c when xTB cannot give it")
    run.add_argument("--predict-basis", help="PREDICT basis set, for methods without their own (default def2-SVP)")
    run.add_argument("--orca", action="store_true", help="QM-validate successful predictions inside the window")
    run.add_argument("--orca-limit", type=int, help="maximum molecules sent to QM in this invocation")
    run.add_argument("--min", "--min-gap", dest="min", type=float, help="lower end of the QM selection window")
    run.add_argument("--max", "--max-gap", dest="max", type=float, help="upper end of the QM selection window")
    run.add_argument("--functional", default="B3LYP", help="QM method (ORCA keyword)")
    run.add_argument("--basis", default="def2-SVP")
    _plot_flags(run)
    report = commands.add_parser("report", help="rebuild reports without running chemistry")
    report.add_argument("run_dir", type=Path)
    _plot_flags(report)
    slurm = commands.add_parser("slurm", help="generate a SLURM script; submit only with --submit")
    slurm.add_argument("--config", type=Path, required=True)
    slurm.add_argument("--script", type=Path, required=True)
    slurm.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_batch(args)
        if args.command == "report":
            from molcurator.batch.reporting import generate_report
            generate_report(native_path(args.run_dir), plots=args.plots)
            print(native_path(args.run_dir) / "report.md")
            return 0
        from molcurator.batch.slurm import prepare
        return prepare(args.config, args.script, submit=args.submit)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
