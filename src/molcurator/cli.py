"""Command-line entry point, installed as `molcurator` (Phase 2, R8.2)."""
from pathlib import Path

import typer

app = typer.Typer(help="MolCurator: an agent that curates molecular benchmark sets.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keeps `run` a named subcommand, so commands like `evaluate` can be added later."""


@app.command()
def run(config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False, help="Run config YAML."),
        run_id: str | None = typer.Option(None, help="Run folder name (default: UTC time + random suffix)."),
        runs_root: Path = typer.Option(Path("data/runs"), help="Where run folders are created.")) -> None:
    """Run the agent for one use case; outputs go to <runs-root>/<run-id>/."""
    from rich.console import Console

    from molcurator.agent.progress import progress_text
    from molcurator.agent.runner import run_agent  # imported here so --help stays instant
    from molcurator.config import load_config
    console = Console()
    state = run_agent(load_config(config), runs_root=runs_root, run_id=run_id,
                      on_event=lambda event: console.print(progress_text(event)))  # live progress (R8.3)
    console.print(f"Run {state['run_id']} stopped: {state['stop_reason']}. Dataset size: {state['dataset_size']}.")
    console.print(f"Outputs: {state['run_dir']}" + (f"\nError: {state['error']}" if state["error"] else ""), markup=False)
    raise typer.Exit(code=1 if state["error"] else 0)
