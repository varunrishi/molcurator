"""Deterministic fake tools for agent tests (Phase 2, R2.3).

FakeTools follows the tool contract in molcurator.tools exactly, but makes up values from the
seed, so the agent can be tested offline, with faults injected on purpose.
"""
import json
import random
from dataclasses import dataclass
from pathlib import Path

from molcurator.agent.decisions import Decided, RuleDecider
from molcurator.schemas import (Candidate, CuratedEntry, GenerationSettings, Prediction,
                                PropertyTarget, QMResult, QMSettings, Status, TrainingExample,
                                TrainResult)


@dataclass
class FakeTools:
    seed: int = 0
    value_center: float = 3.25  # fake xTB values are drawn around this (target units)
    value_spread: float = 0.8
    qm_offset: float = -0.1  # fake QM = xTB + offset + noise: xTB's systematic error
    qm_noise: float = 0.05
    predict_fail_rate: float = 0.0  # share of molecules that fail in predict (R1.6)
    validate_fail_rate: float = 0.0
    repeat_rate: float = 0.0  # share of generated SMILES that repeat earlier ones (R1.5)
    crash_step: str | None = None  # tool that raises as a whole, e.g. "validate" (R1.7)
    ml_noise: float = 0.15  # fake ML estimate = the molecule's fake xTB value + noise of this size
    ml_predict_fail_rate: float = 0.0  # share of molecules that fail in ml_predict (R1.6)

    def _maybe_crash(self, step: str) -> None:
        if self.crash_step == step:  # whole-step failure on purpose (R1.7)
            raise RuntimeError(f"injected crash in {step} (FakeTools.crash_step)")

    def generate(self, parents: list[str], settings: GenerationSettings, round: int, rng_seed: int) -> list[Candidate]:
        """Fake GENERATE: placeholder SMILES, unique per round and index; some repeat their parent."""
        self._maybe_crash("generate")
        rng = random.Random(f"generate-{self.seed}-{rng_seed}-{round}")  # same inputs -> same output
        out = []
        for i in range(settings.n_candidates):
            parent = rng.choice(parents)
            smiles = parent if rng.random() < self.repeat_rate else f"fake-r{round}-{i:03d}"
            out.append(Candidate(id=f"r{round}-c{i:03d}", smiles=smiles, parent_smiles=parent,
                                 round=round, generator=settings.generator))
        return out

    def predict(self, candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]:
        """Fake PREDICT: value set by the SMILES (same molecule, same value); some fail on purpose."""
        self._maybe_crash("predict")
        xyz_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for c in candidates:
            rng = random.Random(f"predict-{self.seed}-{c.smiles}")
            if rng.random() < self.predict_fail_rate:
                out.append(Prediction(candidate_id=c.id, status=Status.failed, error="injected xTB failure"))
                continue
            xyz = xyz_dir / f"{c.id}.xyz"
            xyz.write_text(f"1\n{c.smiles}\nC 0.0 0.0 0.0\n")  # placeholder geometry
            out.append(Prediction(candidate_id=c.id, status=Status.ok, xyz_path=xyz,
                                  value=rng.gauss(self.value_center, self.value_spread)))
        return out

    def train(self, examples: list[TrainingExample], target: PropertyTarget, model_dir: Path) -> TrainResult:
        """Fake TRAIN: saves a tiny JSON "model" (size and mean of the labels); fails on no data."""
        self._maybe_crash("train")
        if not examples:
            raise ValueError("cannot train on zero examples")
        model_dir.mkdir(parents=True, exist_ok=True)
        path = model_dir / f"model-{len(examples)}.json"  # one file per retrain, named by training size
        path.write_text(json.dumps({"n": len(examples), "mean": sum(e.value for e in examples) / len(examples)}))
        return TrainResult(model_path=path, n_examples=len(examples), metrics={"mae": self.ml_noise})

    def ml_predict(self, candidates: list[Candidate], target: PropertyTarget, model: TrainResult) -> list[Prediction]:
        """Fake ML PREDICT: the molecule's fake xTB value (as predict() would give) plus ml_noise."""
        self._maybe_crash("ml_predict")
        if not Path(model.model_path).exists():  # catches the agent passing a stale or wrong model
            raise FileNotFoundError(f"model not found: {model.model_path}")
        out = []
        for c in candidates:
            xtb_rng = random.Random(f"predict-{self.seed}-{c.smiles}")
            xtb_rng.random()  # same draws as predict(): the failure draw first, then the value
            xtb = xtb_rng.gauss(self.value_center, self.value_spread)
            rng = random.Random(f"ml_predict-{self.seed}-{c.smiles}")
            if rng.random() < self.ml_predict_fail_rate:
                out.append(Prediction(candidate_id=c.id, status=Status.failed, error="injected ML failure"))
                continue
            out.append(Prediction(candidate_id=c.id, status=Status.ok, value=xtb + rng.gauss(0, self.ml_noise)))
        return out

    def validate(self, items: list[Prediction], target: PropertyTarget, qm: QMSettings) -> list[QMResult]:
        """Fake VALIDATE: QM = xTB value + systematic offset + noise; some fail on purpose."""
        self._maybe_crash("validate")
        method = f"dft:{qm.functional}/{qm.basis}"
        out = []
        for p in items:
            rng = random.Random(f"validate-{self.seed}-{p.candidate_id}")
            error = "no xTB value to start from" if p.value is None else (
                "injected QM failure" if rng.random() < self.validate_fail_rate else None)
            value = None if error else p.value + self.qm_offset + rng.gauss(0, self.qm_noise)
            out.append(QMResult(candidate_id=p.candidate_id, method=method, value=value, error=error,
                                status=Status.failed if error else Status.ok))
        return out

    def curate(self, entries: list[CuratedEntry], run_dir: Path) -> int:
        """Fake CURATE: appends to run_dir/dataset.jsonl, skipping ids or SMILES already there."""
        self._maybe_crash("curate")
        path = run_dir / "dataset.jsonl"
        rows = [CuratedEntry.model_validate_json(line) for line in path.read_text().splitlines()] if path.exists() else []
        ids, smiles = {r.id for r in rows}, {r.smiles for r in rows}
        run_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for e in entries:
                if e.id in ids or e.smiles in smiles:  # idempotent: re-running on resume adds nothing (R7.2)
                    continue
                ids.add(e.id); smiles.add(e.smiles)
                f.write(e.model_dump_json() + "\n")
        return len(ids)


class ScriptedDecider:
    """Test decider: returns the decisions queued for each node, in order, as if an LLM answered;
    falls back to the rules when a node's queue is empty. `calls` records the order nodes asked."""

    def __init__(self, **queues: list) -> None:  # e.g. continue_or_stop=[ContinueDecision(...), ...]
        self.queues = {node: list(answers) for node, answers in queues.items()}
        self.rules = RuleDecider()
        self.calls: list[str] = []

    def _next(self, node: str, state, config) -> Decided:
        self.calls.append(node)
        queue = self.queues.get(node)
        return Decided(queue.pop(0), source="llm") if queue else getattr(self.rules, node)(state, config)

    def plan_round(self, state, config): return self._next("plan_round", state, config)
    def select_qm_batch(self, state, config): return self._next("select_qm_batch", state, config)
    def continue_or_stop(self, state, config): return self._next("continue_or_stop", state, config)
    def write_summary(self, state, config): return self._next("write_summary", state, config)
