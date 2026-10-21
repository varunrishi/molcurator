"""Starting runs: the run folder, run_agent() and (later) resume_agent() (Phase 2, R8.1, R8.4)."""
import secrets
from datetime import datetime, timezone
from pathlib import Path

import yaml

from molcurator.agent.decisions import Decider, RuleDecider
from molcurator.agent.graph import NODES, build_graph, initial_state
from molcurator.agent.toolset import Toolset
from molcurator.agent.trace import TraceWriter, write_run_start
from molcurator.config import RunConfig


def create_run_dir(config: RunConfig, runs_root: str | Path = "data/runs", run_id: str | None = None) -> Path:
    """Make data/runs/<run_id>/ and save the validated config in it (R8.4); returns the folder.
    A new id is time-sortable with a random suffix; an existing folder is never overwritten."""
    run_id = run_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # raises if that run exists: no accidental overwrite
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    return run_dir


def run_agent(config: RunConfig, tools: Toolset | None = None, decider: Decider | None = None,
              runs_root: str | Path = "data/runs", run_id: str | None = None) -> dict:
    """Run the agent in a new run folder and return the final state (R8.1, R8.4).
    Real tools and the config's decision mode by default; tests pass fakes."""
    if decider is None:
        if config.decisions == "llm":  # checked before the folder exists, so no empty run is left behind
            raise NotImplementedError("the LLM decider is not built yet (Phase 2 step 8); set decisions: rules")
        decider = RuleDecider()
    run_dir = create_run_dir(config, runs_root, run_id)
    trace = TraceWriter(run_dir, run_dir.name)
    write_run_start(trace, config, NODES)
    graph = build_graph(config, tools or Toolset.default(), decider, trace=trace)
    steps = (len(NODES) - 1) * config.budget.max_rounds + 2  # every node per round, plus WRITE SUMMARY
    return graph.invoke(initial_state(run_dir.name, run_dir), {"recursion_limit": steps})
