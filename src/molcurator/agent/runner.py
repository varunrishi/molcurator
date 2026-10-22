"""Starting and resuming runs: the run folder, checkpoints, run_agent() and resume_agent() (Phase 2, R7, R8.1, R8.4)."""
import secrets
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver

from molcurator.agent.decisions import Decider, RuleDecider
from molcurator.agent.graph import build_graph, initial_state, nodes_for
from molcurator.agent.toolset import Toolset
from molcurator.agent.trace import TraceWriter, write_run_start
from molcurator.config import RunConfig, load_config


def create_run_dir(config: RunConfig, runs_root: str | Path = "data/runs", run_id: str | None = None) -> Path:
    """Make data/runs/<run_id>/ and save the validated config in it (R8.4); returns the folder.
    A new id is time-sortable with a random suffix; an existing folder is never overwritten."""
    run_id = run_id or f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # raises if that run exists: no accidental overwrite
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    return run_dir


def open_checkpointer(run_dir: str | Path) -> SqliteSaver:
    """The run's checkpoint store, <run_dir>/checkpoint.sqlite (R7.1). LangGraph saves the state after
    every node, so a resumed run continues after the last completed one. The caller closes saver.conn."""
    # check_same_thread=False: LangGraph may run a node on another thread than the one that opened it
    conn = sqlite3.connect(Path(run_dir) / "checkpoint.sqlite", check_same_thread=False)
    return SqliteSaver(conn)


def default_decider(config: RunConfig) -> Decider:
    """The decider for the config's mode; run_agent and resume_agent share it, so a resumed run
    decides exactly as the original would have (R9.4)."""
    if config.decisions == "llm":
        from molcurator.agent.llm import (
            make_llm_decider,  # imported here: rules-mode runs never load the SDK
        )
        return make_llm_decider(config)
    return RuleDecider()


def run_agent(config: RunConfig, tools: Toolset | None = None, decider: Decider | None = None,
              runs_root: str | Path = "data/runs", run_id: str | None = None,
              on_event: Callable[[dict], None] | None = None) -> dict:
    """Run the agent in a new run folder and return the final state (R8.1, R8.4).
    Real tools and the config's decision mode by default; tests pass fakes."""
    decider = decider or default_decider(config)  # checked before the folder exists, so no empty run is left behind
    run_dir = create_run_dir(config, runs_root, run_id)
    trace = TraceWriter(run_dir, run_dir.name, on_event)
    write_run_start(trace, config, nodes_for(config))
    saver = open_checkpointer(run_dir)
    try:  # the connection is closed even on Ctrl-C; every finished node's checkpoint is already saved
        graph = build_graph(config, tools or Toolset.default(config.predict, config.train), decider, checkpointer=saver, trace=trace)
        steps = (len(nodes_for(config)) - 1) * config.budget.max_rounds + 2  # every node per round, plus WRITE SUMMARY
        return graph.invoke(initial_state(run_dir.name, run_dir),
                            {"configurable": {"thread_id": run_dir.name}, "recursion_limit": steps})  # R7.1
    finally:
        saver.conn.close()


def resume_agent(run_id: str, runs_root: str | Path = "data/runs", tools: Toolset | None = None,
                 decider: Decider | None = None, on_event: Callable[[dict], None] | None = None) -> dict:
    """Continue an interrupted run from its last completed node, with the run's own saved config (R7.2).
    Time spent stopped does not count against max_wall_time (only running time does)."""
    run_dir = Path(runs_root) / run_id
    config = load_config(run_dir / "config.yaml")  # the settings the run started with, not configs/ today
    decider = decider or default_decider(config)
    saver = open_checkpointer(run_dir)
    try:
        trace = TraceWriter(run_dir, run_id, on_event)
        graph = build_graph(config, tools or Toolset.default(config.predict, config.train), decider, checkpointer=saver, trace=trace)
        thread = {"configurable": {"thread_id": run_id}, "recursion_limit": (len(nodes_for(config)) - 1) * config.budget.max_rounds + 2}
        saved = graph.get_state(thread)
        if not saved.next:  # finished (reached WRITE SUMMARY) or never checkpointed
            reason = saved.values.get("stop_reason") if saved.values else "no checkpoint"
            raise ValueError(f"run {run_id} has nothing to resume ({reason})")
        stopped_for = time.time() - datetime.fromisoformat(saved.created_at).timestamp()
        graph.update_state(thread, {"started_at": saved.values["started_at"] + stopped_for})  # option A
        write_run_start(trace, config, nodes_for(config), resumed=True)
        return graph.invoke(None, thread)
    finally:
        saver.conn.close()
