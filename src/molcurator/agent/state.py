"""Agent state shared by the LangGraph nodes and checkpointed after every node (Phase 2, R7.1).

Molecule records live in the state, so a resumed run has everything it needs; bulky XYZ
geometries stay on disk and only their paths are kept. No LLM message history is stored (R3.6).
"""
from typing import Literal, TypedDict

MoleculeStatus = Literal["generated", "duplicate", "predicted", "ml_predicted", "unscored", "failed",
                         "screened_in", "screened_out", "selected", "validated", "curated"]


class MoleculeRecord(TypedDict):
    """Everything the agent knows about one molecule; updated as it moves through a round."""

    id: str
    smiles: str  # canonical, so repeats are found by string comparison (R1.5)
    round: int
    parent: str  # SMILES it was generated from
    status: MoleculeStatus
    xtb: float | None  # PREDICT value
    ml: float | None  # ML PREDICT estimate (R10.4)
    qm: float | None  # VALIDATE value
    qm_method: str | None  # level of theory named by VALIDATE, e.g. "dft:B3LYP/def2-SVP"; CURATE's key
    xyz_path: str | None  # a str, not a Path, so checkpoints hold plain data
    error: str | None  # why it failed (R1.6)


class RoundStats(TypedDict):
    """What happened in one round: the compact summary the continue-or-stop decision sees (R3.3)."""

    round: int
    generated: int
    duplicates: int  # skipped, already seen in the run (R1.5)
    xtb_runs: int  # molecules sent to xTB this round (the random sample, R10.1)
    ml_predicted: int  # molecules scored by the ML model (R10.4)
    unscored: int  # left without any estimate: no xTB value and no model yet (R10.5)
    failed: int  # failed in any tool step (R1.6)
    screened_in: int  # passed the xTB screen (R1.4)
    selected: int  # chosen for QM
    qm_calls: int  # QM calculations actually run (counts against max_qm_calls)
    hits: int  # confirmed in the target by QM and curated


class AgentState(TypedDict):
    """The whole run as LangGraph sees it; each node returns only the fields it changes."""

    run_id: str
    run_dir: str  # the run folder (data/runs/<run_id>/ or a test folder); a str so checkpoints hold plain data
    round: int  # current round, starting at 1
    molecules: dict[str, MoleculeRecord]  # by id; seen SMILES are derived from these + seeds (R1.5)
    round_plan: dict | None  # this round's plan decision (RoundPlan.model_dump()), plain data
    model: dict | None  # latest TrainResult (model_dump()), plain data; None until TRAIN first runs (R10.3)
    qm_batch: list[str]  # ids chosen for VALIDATE this round
    qm_batch_dropped: dict[str, list[str]]  # ids the decider chose that were cut: "not_offered", "over_budget" (R4.2)
    dataset_size: int  # as returned by CURATE
    ml_only_size: int  # rows in dataset_ml_only.csv, written by WRITE SUMMARY at the end of the run
    round_stats: list[RoundStats]  # one per finished round; QM calls used = sum of qm_calls
    stop_reason: str | None  # "llm" | "max_rounds" | "max_qm_calls" | "target_dataset_size" | "max_wall_time" | "error"
    error: str | None  # set when a whole tool step raised (R1.7)
    started_at: float  # time.time() at the start, for max_wall_time (R4.1)
