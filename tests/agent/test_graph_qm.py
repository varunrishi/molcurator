"""The graph with QM on (a qm: section in the config), FakeTools and the rules (Phase 2, R4, R7, R11)."""
import csv
import dataclasses
import json
from pathlib import Path

import pytest

from molcurator.agent.decisions import Decided, QMBatchDecision, RuleDecider
from molcurator.agent.graph import nodes_for
from molcurator.agent.runner import resume_agent, run_agent
from molcurator.agent.summaries import screened_candidates
from molcurator.agent.toolset import Toolset
from molcurator.config import RunConfig, load_config
from tests.agent.fakes import FakeTools
from tests.agent.test_graph import FakeToolsRealCurate, raw_config

QM = {"backend": "orca", "functional": "B3LYP", "basis": "def2-SVP"}  # naming a method turns QM on (R11.1)


def qm_config(n_candidates: int = 100, **budget) -> RunConfig:
    """The HOMO-LUMO config with a qm: section, and a dataset target out of reach so budgets end the run."""
    data = raw_config().model_dump()
    data["qm"] = QM
    data["generation"]["defaults"]["n_candidates"] = n_candidates
    data["budget"].update(target_dataset_size=1000, **budget)
    return RunConfig.model_validate(data)


def trace(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "traces" / "trace.jsonl").read_text().splitlines()]


def test_qm_on_validates_between_screen_and_curate(tmp_path):
    """R11.1-R11.3: SELECT QM BATCH and VALIDATE run after SCREEN; only QM-validated molecules are curated."""
    config = qm_config(max_rounds=2, max_qm_calls=10)
    nodes = nodes_for(config)
    assert nodes[nodes.index("screen"):nodes.index("curate") + 1] == ["screen", "select_qm_batch", "validate", "curate"]
    state = run_agent(config, tools=Toolset.from_object(FakeToolsRealCurate()), runs_root=tmp_path, run_id="qm")
    events = trace(tmp_path / "qm")
    assert events[0]["inputs"]["nodes"] == nodes and events[0]["inputs"]["config"]["qm"]["enabled"] is True
    assert [e["node"] for e in events[1:]] == nodes[:-1] * 2 + ["write_summary"]
    with (tmp_path / "qm" / "dataset.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and len(rows) == state["dataset_size"]
    assert all(r["validated"] == "True" and r["qm"] and r["qm_method"] == "dft:B3LYP/def2-SVP" for r in rows)


def test_rule_spreads_the_qm_budget_over_the_rounds(tmp_path):
    """R4.1: the rule takes an even share of the QM calls left each round, and never more than the budget."""
    state = run_agent(qm_config(max_rounds=5, max_qm_calls=6), tools=Toolset.from_object(FakeTools()),
                      runs_root=tmp_path, run_id="qm")
    assert [s["qm_calls"] for s in state["round_stats"]] == [2, 1, 1, 1, 1]  # 6/5, 4/4, 3/3, 2/2, 1/1, rounded up


class GreedyDecider(RuleDecider):
    """Asks for every candidate offered, plus an id it was not offered and a repeat, as a bad LLM answer might."""

    def select_qm_batch(self, state, config):
        ids = [m["id"] for m in screened_candidates(state, config)]
        return Decided(QMBatchDecision(select=["not-a-candidate", *ids, ids[0]], reason="all of them"), source="llm")


def test_qm_batch_is_cut_to_the_budget_and_the_run_stops(tmp_path):
    """R4.2, R4.3: unknown ids are dropped, the batch is cut to the QM calls left (recorded), and the run stops."""
    state = run_agent(qm_config(max_rounds=5, max_qm_calls=5), tools=Toolset.from_object(FakeTools()),
                      decider=GreedyDecider(), runs_root=tmp_path, run_id="qm")
    assert state["stop_reason"] == "max_qm_calls" and [s["qm_calls"] for s in state["round_stats"]] == [5]
    line = next(e for e in trace(tmp_path / "qm") if e["node"] == "select_qm_batch")
    batch, dropped = line["outputs"]["qm_batch"], line["outputs"]["qm_batch_dropped"]
    assert len(batch) == 5 and dropped["not_offered"] == ["not-a-candidate"]
    assert len(batch) + len(dropped["over_budget"]) == len(set(batch + dropped["over_budget"])) > 5  # repeat counted once


class MLOnlyDecider(RuleDecider):
    """Sends only molecules that have just an ML value (no geometry yet) to QM."""

    def select_qm_batch(self, state, config):
        ids = [m["id"] for m in screened_candidates(state, config) if m["xtb"] is None]
        return Decided(QMBatchDecision(select=ids, reason="ML-only"), source="llm")


def test_ml_only_batch_molecules_get_xtb_before_qm(tmp_path):
    """R11.2 (option A, plan.md): an ML-only molecule gets xTB first; if that fails, it skips QM and costs no QM call."""
    state = run_agent(qm_config(n_candidates=1000, max_rounds=1, max_qm_calls=20),
                      tools=Toolset.from_object(FakeTools(predict_fail_rate=0.3)), decider=MLOnlyDecider(),
                      runs_root=tmp_path, run_id="qm")
    batch = [state["molecules"][i] for i in state["qm_batch"]]
    ok, no_xtb = [m for m in batch if m["xyz_path"]], [m for m in batch if not m["xyz_path"]]
    assert ok and no_xtb and all(m["ml"] is not None for m in batch)  # seeded: some xTB runs fail, some succeed
    # validated, then curated if the QM value is inside the window
    assert all(m["xtb"] is not None and m["status"] in ("validated", "curated") and m["qm"] is not None for m in ok)
    assert all(m["status"] == "failed" and m["qm"] is None and m["error"] == "injected xTB failure" for m in no_xtb)
    stats = state["round_stats"][0]
    assert (stats["selected"], stats["qm_calls"], stats["xtb_runs"]) == (len(batch), len(ok), 200 + len(batch))


def test_interrupted_qm_run_resumes_to_the_same_result(tmp_path):
    """R7.2: Ctrl-C in CURATE, right after VALIDATE, then resume: the same result as a run that was not interrupted."""
    config, tools = qm_config(max_rounds=2, max_qm_calls=10), Toolset.from_object(FakeTools())
    full = run_agent(config, tools=tools, runs_root=tmp_path, run_id="full")
    def ctrl_c(*args): raise KeyboardInterrupt  # not caught by guarded, like a real Ctrl-C
    with pytest.raises(KeyboardInterrupt):
        run_agent(config, tools=dataclasses.replace(tools, curate=ctrl_c), runs_root=tmp_path, run_id="cut")
    resumed = resume_agent("cut", runs_root=tmp_path, tools=tools)
    assert all(resumed[k] == full[k] for k in ("dataset_size", "round_stats", "stop_reason"))
    names = lambda state: {i: {**m, "xyz_path": m["xyz_path"] and Path(m["xyz_path"]).name}  # noqa: E731
                           for i, m in state["molecules"].items()}  # the run folder differs, nothing else
    assert names(resumed) == names(full) and any(m["qm"] is not None for m in full["molecules"].values())
