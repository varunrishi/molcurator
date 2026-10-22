"""Run configuration: one YAML file per use case, validated once at startup (Phase 2, R1.2)."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from rdkit import Chem

from molcurator.schemas import GenerationSettings, PropertyTarget, QMSettings


class StrictModel(BaseModel):
    """Config models reject unknown keys, so a misspelled YAML field raises instead of silently
    falling back to its default (e.g. `max_qm_call: 5` would otherwise leave 20 QM calls)."""

    model_config = ConfigDict(extra="forbid")


class ScreeningSettings(StrictModel):
    margin: float = Field(default=0.2, ge=0)  # widens the target window for xTB's systematic error (R1.4)


class BudgetSettings(StrictModel):
    """Hard limits, enforced in code whatever the LLM decides (R4.1, R4.3)."""

    max_rounds: int = Field(default=5, ge=1)
    max_qm_calls: int = Field(default=20, ge=0)  # QM (ORCA DFT) is the expensive step
    target_dataset_size: int = Field(default=10, ge=1)
    max_wall_time: float = Field(default=3600, gt=0)  # seconds


class GenerationLimits(StrictModel):
    """What the plan-round decision may choose; tighter than the schema's hard bounds (R3.1)."""

    generators: list[str] = ["stoned_selfies"]
    max_candidates: int = Field(default=1000, ge=1, le=1000)
    max_mutation_strength: int = Field(default=3, ge=1, le=5)
    defaults: GenerationSettings = GenerationSettings()  # round 1, and the fallback rule (R3.5)

    @model_validator(mode="after")
    def _defaults_within_limits(self) -> "GenerationLimits":
        d = self.defaults  # round 1 and the fallback rule must obey the same limits as the LLM
        if d.generator not in self.generators or d.n_candidates > self.max_candidates or d.mutation_strength > self.max_mutation_strength:
            raise ValueError("generation.defaults must lie within the generation limits")
        return self


class LLMSettings(StrictModel):
    provider: Literal["anthropic", "openai"] | None = None  # None: LLM_PROVIDER from .env (R9.1)
    model: str | None = None  # None: LLM_MODEL from .env
    timeout_s: float = Field(default=10, gt=0)  # after this, the node's rule decides (R9.5)
    max_table_rows: int = Field(default=20, ge=1)  # candidates shown to the QM-batch decision (R3.2)


class PredictSettings(StrictModel):
    # PREDICT on a random sample of this many new candidates per round (R10.1). The name predates
    # TD-DFT PREDICT: targets xTB cannot give (s1_t1_gap) run B97-3c instead, see tools/predict.py.
    n_xtb: int = Field(default=200, ge=1)


class TrainSettings(StrictModel):
    # Train once this many molecules have xTB values (R10.2). Below predict.n_xtb (200), because ~7% of
    # xTB runs fail: 200 runs give ~186 values, and 200 would make round 1 skip TRAIN and leave its rest unscored.
    min_examples: int = Field(default=150, ge=1)


class QMConfig(QMSettings):
    """The contract's QM settings plus whether to run QM at all; validate() still gets QMSettings fields."""

    model_config = ConfigDict(extra="forbid")  # extends the contract's model, so not a StrictModel

    # On as soon as a config writes a qm: section naming its method; `enabled: false` keeps the
    # section but skips QM. With no qm: section, RunConfig's default below has QM off (R11.1).
    enabled: bool = True

    @model_validator(mode="after")
    def _not_xtb(self) -> "QMConfig":
        # VALIDATE checks PREDICT (GFN2-xTB by default), so an xTB method here would validate xTB with xTB.
        from molcurator.chem.backends import xtb_validation_message
        if self.enabled and (warning := xtb_validation_message(self.functional)):
            raise ValueError(warning)
        return self


class RunConfig(StrictModel):
    """One run: what to look for, where to start, and the limits (configs/<use case>.yaml)."""

    target: PropertyTarget
    seeds: list[str] = Field(min_length=1)  # starting SMILES for round 1 (R1.3)
    generation: GenerationLimits = GenerationLimits()
    screening: ScreeningSettings = ScreeningSettings()
    predict: PredictSettings = PredictSettings()
    train: TrainSettings = TrainSettings()
    qm: QMConfig = QMConfig(enabled=False)  # no qm: section: QM is slow, so it is skipped (R11.1)
    budget: BudgetSettings = BudgetSettings()
    decisions: Literal["llm", "rules"] = "llm"  # "rules": no LLM calls at all (R9.4)
    llm: LLMSettings = LLMSettings()
    rng_seed: int = 0  # passed to generate, so a run is repeatable (R7.2)

    @field_validator("seeds")
    @classmethod
    def _canonical_seeds(cls, seeds: list[str]) -> list[str]:
        # Repeats are found by comparing canonical SMILES (R1.5), so the seeds must be canonical too.
        canonical = []
        for smiles in seeds:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                raise ValueError(f"seed is not a valid SMILES: {smiles!r}")
            canonical.append(Chem.MolToSmiles(mol))
        return canonical


def load_config(path: str | Path) -> RunConfig:
    """Read and validate a run config YAML file; errors name the file and the bad fields."""
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}  # safe_load builds plain data only; {} for an empty file
    try:
        return RunConfig.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"invalid run config {path}:\n{e}") from e
