"""Batch CLI dispatch for independent execution, reporting and SLURM modules."""
import argparse
from pathlib import Path
import subprocess
import sys
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate
from .batch_inputs import read_candidates
from .batch_runtime import run_lock, check_allocation
from .fileio import native_path


def run_batch(args):
    # Compatibility facade; Python callers may use batch_runner directly.
    from .batch_runner import run_batch as execute
    return execute(args, predict_fn=predict, validate_fn=validate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="predict CSV or SMILES input and write reports")
    run.add_argument("input", type=Path)
    run.add_argument("--format", choices=("auto", "csv", "smi"), default="auto")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--orca", action="store_true", help="validate selected successful xTB predictions")
    run.add_argument("--orca-limit", type=int, help="maximum selected ORCA inputs per invocation, including cache hits")
    run.add_argument("--min-gap", type=float, help="minimum xTB gap for ORCA selection in eV")
    run.add_argument("--max-gap", type=float, help="maximum xTB gap for ORCA selection in eV")
    run.add_argument("--functional", default="B3LYP")
    run.add_argument("--basis", default="def2-SVP")
    plot_run = run.add_mutually_exclusive_group()
    plot_run.add_argument("--plots", action="store_true", help="enable optional PNG plots")
    plot_run.add_argument("--no-plots", dest="plots", action="store_false", help="disable plots (default)")
    run.set_defaults(plots=False)
    report = commands.add_parser("report", help="regenerate reports without running chemistry")
    report.add_argument("run_dir", type=Path)
    plot_report = report.add_mutually_exclusive_group()
    plot_report.add_argument("--plots", action="store_true", help="enable optional PNG plots")
    plot_report.add_argument("--no-plots", dest="plots", action="store_false", help="disable plots (default)")
    report.set_defaults(plots=False)
    slurm = commands.add_parser("slurm", help="generate a SLURM script; submit only with --submit")
    slurm.add_argument("--config", type=Path, required=True)
    slurm.add_argument("--script", type=Path, required=True)
    slurm.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_batch(args)
        if args.command == "report":
            from .reporting import generate_report
            generate_report(native_path(args.run_dir), plots=args.plots)
            print(native_path(args.run_dir) / "report.md")
            return 0
        from .slurm import prepare
        return prepare(args.config, args.script, submit=args.submit)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
