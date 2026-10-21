"""Data contract between the agent and the tools (Phase 2, R2.1).

Every tool takes and returns these Pydantic models, so the agent never depends on how a
tool works internally, and fake tools in tests can follow exactly the same contract.
"""
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class PropertyTarget(BaseModel):
    """The property the run is looking for, e.g. a HOMO-LUMO gap window (from the config)."""

    name: str  # e.g. "homo_lumo_gap", "s1_t1_gap"
    min: float | None = None
    max: float | None = None
    units: str = "eV"

    @model_validator(mode="after")
    def _check_bounds(self) -> "PropertyTarget":
        # A target with no bound would accept every molecule; min > max accepts none.
        if self.min is None and self.max is None or (self.min is not None and self.max is not None and self.min > self.max):
            raise ValueError("target needs min and/or max, with min <= max")
        return self


class Status(str, Enum):
    """Per-molecule result of a tool step. Tools mark failures instead of dropping molecules (R2.4)."""

    ok = "ok"
    failed = "failed"


class Candidate(BaseModel):
    """One molecule produced by GENERATE."""

    id: str  # unique within the run, e.g. "r2-c017"
    smiles: str  # canonical SMILES, so repeats can be detected by string comparison (R1.5)
    parent_smiles: str  # the molecule it was generated from (provenance)
    round: int = Field(ge=1)
    generator: str  # e.g. "stoned_selfies"


class ToolResult(BaseModel):
    """Per-molecule result shared by PREDICT and VALIDATE: one per input, never dropped (R2.4)."""

    candidate_id: str
    status: Status
    value: float | None = None  # the target property at this tool's level of theory
    error: str | None = None

    @model_validator(mode="after")
    def _check_status(self) -> "ToolResult":
        # "ok" without a value or "failed" without a reason would hide a tool bug from the agent.
        if (self.status is Status.ok) != (self.value is not None) or (self.status is Status.failed and not self.error):
            raise ValueError("ok results need a value; failed results need an error and no value")
        return self


class Prediction(ToolResult):
    xyz_path: Path | None = None  # selected MMFF94 geometry; VALIDATE uses it for a single point


class QMResult(ToolResult):
    method: str  # level of theory, e.g. "dft:B3LYP/def2-SVP"


class GenerationSettings(BaseModel):
    """How GENERATE should produce this round's candidates (chosen by the plan-round decision)."""

    generator: str = "stoned_selfies"
    n_candidates: int = Field(default=100, ge=1, le=1000)
    mutation_strength: int = Field(default=2, ge=1, le=5)  # e.g. SELFIES edits per molecule


class QMSettings(BaseModel):
    """Level of theory for VALIDATE; fixed by the config so results stay comparable."""

    backend: str = "orca"  # or "pyscf"
    functional: str = "B3LYP"
    basis: str = "def2-SVP"


class CuratedEntry(BaseModel):
    """One verified molecule in the benchmark set (CURATE input)."""

    id: str; smiles: str; xyz_path: Path
    properties: dict[str, float]  # method -> value, e.g. {"xtb": 3.31, "dft:B3LYP/def2-SVP": 3.18}
    provenance: dict[str, str]  # seed, parent, generator, round
