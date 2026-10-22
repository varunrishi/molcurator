"""Run configuration: one YAML file per use case, validated once at startup (Phase 2, R1.2)."""
import csv
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
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


CORRECTED_PROPERTY = "homo_lumo_gap"  # the only target the xTB -> DFT-like correction is fitted for


class CorrectionSettings(StrictModel):
    """On-top correction of xTB gaps to DFT-like values, applied at the end of PREDICT:
    corrected = slope * xTB + intercept, fitted on paired gaps by scripts/fit_xtb_correction.py."""

    slope: float = Field(gt=0)  # positive: the correction must keep the order of the gaps
    intercept: float
    residual_sd: float = Field(ge=0)  # the fit's typical error (eV), a guide for screening.margin
    xtb_range: tuple[float, float]  # raw xTB gaps the fit was made on; outside it, it extrapolates
    fitted_on: str  # what the fit used, recorded in the trace with the config

    @model_validator(mode="after")
    def _range_in_order(self):
        if self.xtb_range[0] > self.xtb_range[1]:
            raise ValueError(f"xtb_range must be [low, high], got {list(self.xtb_range)}")
        return self


class PredictSettings(StrictModel):
    # PREDICT on a random sample of this many new candidates per round (R10.1). The name predates
    # TD-DFT PREDICT: targets xTB cannot give (s1_t1_gap) run B97-3c instead, see tools/predict.py.
    n_xtb: int = Field(default=200, ge=1)
    # PREDICT's level of theory. None: GFN2-xTB when xTB can give the target, else B97-3c.
    # Any ORCA method or xTB name (gfn2-xtb, gfn1-xtb); basis only for methods without their own.
    method: str | None = None
    basis: str | None = None
    correction: CorrectionSettings | None = None  # none: PREDICT keeps the raw xTB values


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

    @model_validator(mode="after")
    def _target_is_a_property(self) -> "RunConfig":
        # A target the tools cannot compute, or a window in the wrong unit, would only fail (or
        # mislead) once PREDICT runs; checked here instead. Units left out take the property's own.
        from molcurator.chem.backends import check_target
        given = self.target.units if "units" in self.target.model_fields_set else None
        self.target.units = check_target(self.target.name, given)
        return self

    @model_validator(mode="after")
    def _predict_level_works(self) -> "RunConfig":
        # Checked here, so an impossible PREDICT level stops the run before any calculation.
        from molcurator.tools.predict import check_predict_level
        qm = (self.qm.functional, self.qm.basis) if self.qm.enabled else (None, None)
        check_predict_level(self.target.name, self.predict.method, self.predict.basis, *qm)
        return self

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

    @model_validator(mode="after")
    def _correction_only_for_gaps(self) -> "RunConfig":
        # The correction is fitted on xTB vs DFT HOMO-LUMO gaps; for any other property it would be wrong.
        if self.predict.correction is not None and self.target.name != CORRECTED_PROPERTY:
            raise ValueError(f"predict.correction applies to {CORRECTED_PROPERTY} only, not {self.target.name!r}; "
                             "remove it from this config")
        # ...and it is fitted for GFN2-xTB gaps: another PREDICT method needs its own fit.
        method = self.predict.method
        if self.predict.correction is not None and method is not None and method.strip().lower() != "gfn2-xtb":
            raise ValueError(f"predict.correction is fitted for GFN2-xTB, not predict.method {method!r}; "
                             "remove the correction or fit one for this method (scripts/fit_xtb_correction.py)")
        return self


def read_seeds_file(path: Path) -> list[str]:
    """The `smiles` column of a seed CSV (data/seeds/README.md), in file order; blank cells are skipped."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if "smiles" not in (reader.fieldnames or []):
            raise ValueError(f"seeds file {path} has no 'smiles' column")
        return [row["smiles"].strip() for row in reader if (row["smiles"] or "").strip()]


def load_config(path: str | Path) -> RunConfig:
    """Read and validate a run config YAML file; errors name the file and the bad fields.
    `seeds_file:` (a CSV path, relative to the YAML file) may replace `seeds:`; it is read here, so the
    RunConfig, and the config.yaml a run saves, hold the seed SMILES themselves."""
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}  # safe_load builds plain data only; {} for an empty file
    if "seeds_file" in data:
        if "seeds" in data:
            raise ValueError(f"invalid run config {path}: give seeds or seeds_file, not both")
        data["seeds"] = read_seeds_file(path.parent / data.pop("seeds_file"))
    try:
        return RunConfig.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"invalid run config {path}:\n{e}") from e
