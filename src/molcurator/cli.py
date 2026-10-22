"""Command-line entry point, installed as `molcurator` (Phase 2, R8.2)."""
from pathlib import Path

import typer

app = typer.Typer(help="MolCurator: an agent that curates molecular benchmark sets.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keeps `run` a named subcommand, so commands like `evaluate` can be added later."""


@app.command()
def run(config: Path | None = typer.Option(None, "--config", "-c", exists=True, dir_okay=False, help="Run config YAML."),
        resume: str | None = typer.Option(None, help="Continue this interrupted run, with its saved config."),
        run_id: str | None = typer.Option(None, help="Run folder name (default: UTC time + random suffix)."),
        runs_root: Path = typer.Option(Path("data/runs"), help="Where run folders are created.")) -> None:
    """Run the agent for one use case, or --resume an interrupted run; outputs go to <runs-root>/<run-id>/."""
    from rich.console import Console

    from molcurator.agent.progress import progress_text
    from molcurator.agent.runner import resume_agent, run_agent  # imported here so --help stays instant
    from molcurator.config import load_config
    if (config is None) == (resume is None):
        raise typer.BadParameter("give either --config for a new run or --resume <run_id>, not both")
    console = Console()
    show = lambda event: console.print(progress_text(event))  # noqa: E731 (live progress, R8.3)
    if resume:
        try:
            state = resume_agent(resume, runs_root, on_event=show)
        except ValueError as e:  # nothing to resume: the run finished or has no checkpoint
            console.print(f"Cannot resume: {e}", markup=False)
            raise typer.Exit(code=2)
    else:
        state = run_agent(load_config(config), runs_root=runs_root, run_id=run_id, on_event=show)
    console.print(f"Run {state['run_id']} stopped: {state['stop_reason']}. Dataset size: {state['dataset_size']}.")
    console.print(f"Outputs: {state['run_dir']}" + (f"\nError: {state['error']}" if state["error"] else ""), markup=False)
    raise typer.Exit(code=1 if state["error"] else 0)


@app.command()
def seeds(prop: str = typer.Option(..., "--property", "-p", help="QM9 column, e.g. gap, homo, lumo, mu, alpha."),
          lo: float | None = typer.Option(None, "--min", help="Lower bound (eV for gap/homo/lumo)."),
          hi: float | None = typer.Option(None, "--max", help="Upper bound (eV for gap/homo/lumo)."),
          n: int = typer.Option(5, "--n", "-n", min=1, help="How many seeds to suggest."),
          out: Path | None = typer.Option(None, "--out", "-o", dir_okay=False, help="Also write the seeds to this CSV."),
          qm9_path: Path = typer.Option(Path("data/seeds/qm9.csv"), "--qm9", help="QM9 CSV; downloaded here if missing.")) -> None:
    """Suggest seed molecules from QM9 whose property lies in [--min, --max]."""
    from rich.console import Console
    from rich.table import Table

    from molcurator.chem.qm9 import QM9_URL, load_qm9, suggest_seeds
    console = Console()
    if not qm9_path.exists():
        console.print(f"Downloading QM9 (28 MB) to {qm9_path} from {QM9_URL}", markup=False)
    try:
        picked, counts = suggest_seeds(load_qm9(qm9_path), prop, lo, hi, n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    dropped = ", ".join(f"{k} {v}" for k, v in counts.items() if k not in ("in window", "usable"))
    console.print(f"{counts['in window']} QM9 molecules in window, {counts['usable']} usable"
                  + (f" (dropped: {dropped})" if dropped else ""), markup=False)
    if picked.empty:
        console.print("No usable seeds in this window; widen it.")
        raise typer.Exit(code=1)
    table = Table("mol_id", f"{prop} ({picked['unit'][0]})", "heavy atoms")
    table.add_column("smiles", no_wrap=True)  # the column people copy; never truncate it
    for r in picked.itertuples(index=False):
        table.add_row(r.mol_id, f"{getattr(r, f'qm9_{prop}'):.4g}", str(r.heavy_atoms), r.smiles)
    console.print(table)
    if len(picked) < n:
        console.print(f"Only {len(picked)} distinct scaffolds available; asked for {n}.")
    if out:
        picked.to_csv(out, index=False)
        console.print(f"Wrote {out}", markup=False)
