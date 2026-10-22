"""The v1 graph end to end with FakeTools and the rules, QM off (Phase 2, R1, R4, R10)."""
import csv
from pathlib import Path

from molcurator.agent.decisions import RuleDecider
from molcurator.agent.graph import NODES, build_graph, initial_state
from molcurator.agent.toolset import Toolset
from molcurator.agent.trace import TraceWriter, write_run_start
from molcurator.config import RunConfig, load_config
from molcurator.tools.curate import curate
from tests.agent.fakes import FakeTools

CONFIG = Path(__file__).parents[2] / "configs" / "homo_lumo.yaml"  # independent of pytest's working directory


class FakeToolsRealCurate(FakeTools):
    """Fake chemistry, real CURATE: the end-of-run export reads the real dataset.csv."""
    curate = staticmethod(curate)


def run_graph(tmp_path, tools: FakeTools | None = None, n_candidates: int | None = None, **budget) -> dict:
    """Run the HOMO-LUMO config to the end and return the final state; overrides are re-validated."""
    data = load_config(CONFIG).model_dump()
    data["budget"].update(budget)
    if n_candidates is not None:
        data["generation"]["defaults"]["n_candidates"] = n_candidates
    config = RunConfig.model_validate(data)
    trace = TraceWriter(tmp_path, "test")  # every test run is traced, as the runner will do (R6.1)
    write_run_start(trace, config, NODES)
    graph = build_graph(config, Toolset.from_object(tools or FakeTools()), RuleDecider(), trace=trace)
    # 9 nodes per round plus WRITE SUMMARY; a wrongly looping graph fails instead of hanging
    return graph.invoke(initial_state("test", tmp_path), {"recursion_limit": 9 * config.budget.max_rounds + 2})


def test_v1_run_ends_with_summary_and_dataset(tmp_path):
    """R1.1, R1.6, R3.4, R4.4: a whole rules-only run, QM off, stops at the target dataset size."""
    state = run_graph(tmp_path)
    assert state["error"] is None and state["stop_reason"] == "target_dataset_size"
    assert len(state["round_stats"]) == 1
    statuses = [m["status"] for m in state["molecules"].values()]
    assert "generated" not in statuses  # every candidate was scored, failed or marked duplicate
    assert state["dataset_size"] == statuses.count("curated") >= 10
    assert "Stopped because: target_dataset_size." in (tmp_path / "summary.md").read_text()


def test_budget_limit_ends_run_after_the_round(tmp_path):
    """R4.3, R4.4: with the dataset target out of reach, the run loops until max_rounds, then stops."""
    state = run_graph(tmp_path, target_dataset_size=1000, max_rounds=3)
    assert state["error"] is None and state["stop_reason"] == "max_rounds"
    assert [s["round"] for s in state["round_stats"]] == [1, 2, 3]
    assert state["dataset_size"] == sum(s["hits"] for s in state["round_stats"])
    assert {m["round"] for m in state["molecules"].values()} == {1, 2, 3}


def test_xtb_sample_trains_model_and_ml_scores_the_rest(tmp_path):
    """R10.1-R10.5: xTB on a fifth of the candidates per round, TRAIN refits on all xTB data, ML scores the rest."""
    n = 1000
    xtb = round(0.2 * n)
    assert load_config(CONFIG).predict.n_xtb == xtb  # the fraction rests on the config's n_xtb
    state = run_graph(tmp_path, tools=FakeToolsRealCurate(), n_candidates=n, target_dataset_size=10 * n, max_rounds=2)
    for s in state["round_stats"]:
        assert (s["generated"], s["xtb_runs"], s["ml_predicted"], s["unscored"]) == (n, xtb, n - xtb, 0)
    assert state["model"]["n_examples"] == 2 * xtb  # refit on both rounds' xTB values
    assert (tmp_path / "models" / "round-2").is_dir()
    # The end-of-run export holds exactly the curated molecules that have only an ML value
    ml_only = {m["id"] for m in state["molecules"].values()
               if m["status"] == "curated" and m["ml"] is not None and m["xtb"] is None}
    with (tmp_path / "dataset_ml_only.csv").open(newline="") as f:
        assert {r["id"] for r in csv.DictReader(f)} == ml_only and len(ml_only) == state["ml_only_size"] > 0
    assert f"ML-only molecules: {len(ml_only)} (dataset_ml_only.csv)" in (tmp_path / "summary.md").read_text()


def test_crashed_tool_step_stops_run_and_writes_summary(tmp_path):
    """R1.7, R4.4: a tool that raises ends the run at WRITE SUMMARY, with the failing step named."""
    state = run_graph(tmp_path, tools=FakeTools(crash_step="predict"))
    assert state["stop_reason"] == "error" and state["error"].startswith("predict: ")
    assert state["round_stats"] == [] and state["dataset_size"] == 0  # skipped the rest of the round
    assert "Stopped because: error." in (tmp_path / "summary.md").read_text()
