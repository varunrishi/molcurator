"""Validated settings shared by direct tools and the agent without changing contracts."""
from contextvars import ContextVar
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .environment import load_binary_environment


class ChemistrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    nconfs: int = Field(default=30, ge=1, le=10000, strict=True)
    random_seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    mmff_max_iterations: int = Field(default=500, ge=1, strict=True)
    mmff_force_tolerance: float = Field(default=0.0001, gt=0)
    mmff_energy_tolerance: float = Field(default=0.000001, gt=0)
    temperature_k: float = Field(default=298.15, gt=0)
    rms_cutoff_angstrom: float = Field(default=0.25, gt=0)
    orca_nprocs: int = Field(default=1, ge=1, strict=True)
    orca_maxcore_mb: int = Field(default=2000, ge=1, strict=True)
    timeout_s: float = Field(default=600, gt=0)
    cache_enabled: bool = Field(default=True, strict=True)
    cache_epoch: str = "1"


def load_settings() -> ChemistrySettings:
    load_binary_environment()
    path = os.environ.get("MOLCURATOR_CHEM_CONFIG")
    values = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(values, dict):
        raise ValueError("chemistry configuration must be a JSON object")
    # Preserve the existing explicit timeout environment override.
    if os.environ.get("MOLCURATOR_QC_TIMEOUT_S"):
        values["timeout_s"] = float(os.environ["MOLCURATOR_QC_TIMEOUT_S"])
    return ChemistrySettings.model_validate(values)


active_settings = ContextVar("chemistry_settings", default=None)
