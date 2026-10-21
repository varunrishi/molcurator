"""The agent's LangGraph graph: decision nodes, routing and build_graph (Phase 2, R1.1).

The round is a fixed sequence of nodes; the decider only fills in values (parents, QM batch,
continue or stop), never the order. Budgets are checked in code after every round (R4.3).
"""
import time
from collections.abc import Callable
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from molcurator.agent import nodes
from molcurator.agent.budgets import budget_stop_reason
from molcurator.agent.decisions import Decider
from molcurator.agent.state import AgentState
from molcurator.agent.toolset import Toolset
from molcurator.agent.trace import RecordingDecider, TraceWriter, traced
from molcurator.config import RunConfig

TOOL_STEPS = ["generate", "predict", "train", "ml_predict", "screen", "curate", "close_round"]  # v1 order, QM off
NODES = ["plan_round", *TOOL_STEPS, "continue_or_stop", "write_summary"]  # for the run_start line (#13)


def initial_state(run_id: str, run_dir: str | Path) -> AgentState:
    """The state a new run starts from: round 1, nothing generated yet. started_at is now (R4.1)."""
    return AgentState(run_id=run_id, run_dir=str(run_dir), round=1, molecules={}, round_plan=None, model=None,
                      qm_batch=[], dataset_size=0, round_stats=[], stop_reason=None, error=None,
                      started_at=time.time())


def plan_round_node(state: AgentState, config: RunConfig, decider: Decider) -> dict:
    """PLAN ROUND: the decider chooses this round's parents and generation settings (R3.1).
    Clearing qm_batch here starts every round clean, so no step sees last round's batch."""
    decided = decider.plan_round(state, config)
    return {"round_plan": decided.decision.model_dump(), "qm_batch": []}


def continue_or_stop_node(state: AgentState, config: RunConfig, decider: Decider) -> dict:
    """CONTINUE OR STOP: after each round, the decider chooses; budget limits always win (R3.3, R4.3).
    Continuing moves the run to the next round, so PLAN ROUND sees the new round number."""
    limit = budget_stop_reason(state, config.budget)
    if limit:  # checked first: the decider can never extend a run past a budget
        return {"stop_reason": limit}
    if decider.continue_or_stop(state, config).decision.decision == "stop":
        return {"stop_reason": "llm"}  # stopped early with budget left (never happens with the rules)
    return {"round": state["round"] + 1}


def write_summary_node(state: AgentState, config: RunConfig, decider: Decider) -> dict:
    """WRITE SUMMARY: the last node of every run, errors included; saves summary.md (R3.4, R1.7).
    The error route skips CONTINUE OR STOP, so the stop reason is set here before the decider writes."""
    stop_reason = state["stop_reason"] or ("error" if state["error"] else None)
    decided = decider.write_summary({**state, "stop_reason": stop_reason}, config)
    run_dir = Path(state["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)  # a run that fails early may not have made it yet
    (run_dir / "summary.md").write_text(decided.decision.summary + "\n")
    return {"stop_reason": stop_reason}


def guarded(name: str, node: Callable[[AgentState], dict]) -> Callable[[AgentState], dict]:
    """Run a tool node; if the whole step raises, store the error instead of crashing the run (R1.7).
    The routing then sends the run straight to WRITE SUMMARY, which still saves summary.md."""
    def run(state: AgentState) -> dict:
        try:
            return node(state)
        except Exception as exc:  # any tool failure: missing binary, contract violation, bad parent id
            return {"error": f"{name}: {type(exc).__name__}: {exc}"}
    return run


def bind(fn: Callable, *extra) -> Callable[[AgentState], dict]:
    """fn(state, *extra) as a one-argument node; LangGraph would replace a parameter named `config`."""
    return lambda state: fn(state, *extra)


def build_graph(config: RunConfig, tools: Toolset, decider: Decider, checkpointer=None,
                trace: TraceWriter | None = None):
    """The v1 round loop: PLAN ROUND -> tool steps -> CONTINUE OR STOP -> next round or WRITE SUMMARY.
    With a trace writer, every node writes one trace line when it finishes (R6.1, R6.2)."""
    if config.qm.enabled:
        raise NotImplementedError("QM steps are not wired into the v1 graph; set qm.enabled: false")
    recorder = RecordingDecider(decider) if trace else decider
    def add(name, node, decision=False):  # tracing wraps outside guarded, so a crash still gets a line
        g.add_node(name, traced(name, node, trace, recorder if decision else None) if trace else node)
    g = StateGraph(AgentState)
    add("plan_round", bind(plan_round_node, config, recorder), decision=True)
    for name in TOOL_STEPS:
        add(name, guarded(name, bind(getattr(nodes, f"{name}_node"), config, tools)))
    add("continue_or_stop", bind(continue_or_stop_node, config, recorder), decision=True)
    add("write_summary", bind(write_summary_node, config, recorder), decision=True)
    g.add_edge(START, "plan_round")
    g.add_edge("plan_round", TOOL_STEPS[0])
    for name, nxt in zip(TOOL_STEPS, [*TOOL_STEPS[1:], "continue_or_stop"]):  # a crashed step ends the run (R1.7)
        g.add_conditional_edges(name, lambda s, nxt=nxt: "write_summary" if s["error"] else nxt)
    g.add_conditional_edges("continue_or_stop", lambda s: "write_summary" if s["stop_reason"] else "plan_round")
    g.add_edge("write_summary", END)
    return g.compile(checkpointer=checkpointer)
