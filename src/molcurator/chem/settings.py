# Runtime settings for the chemistry tools: conformer search, ORCA resources and timeouts.
# Defaults below; overridden by the JSON file named by MOLCURATOR_CHEM_CONFIG and by
# MOLCURATOR_QC_TIMEOUT_S (both may be set in .env). A batch run freezes one copy for the
# whole invocation (active_settings), so editing the file mid-run changes nothing.
import json
import os
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class ChemistrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    nconfs: int = Field(default=30, ge=1, le=10000, strict=True)  # RDKit conformers embedded per molecule
    random_seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    mmff_max_iterations: int = Field(default=500, ge=1, strict=True)
    mmff_force_tolerance: float = Field(default=0.0001, gt=0)
    mmff_energy_tolerance: float = Field(default=0.000001, gt=0)
    temperature_k: float = Field(default=298.15, gt=0)  # for the force-field Boltzmann weight
    rms_cutoff_angstrom: float = Field(default=0.25, gt=0)  # conformers closer than this count once
    orca_nprocs: int = Field(default=1, ge=1, strict=True)  # > 1 needs Open MPI: OPENMPI_HOME, or mpirun on PATH
    orca_maxcore_mb: int = Field(default=2000, ge=1, strict=True)
    timeout_s: float = Field(default=600, gt=0)  # per ORCA process


active_settings: ContextVar[ChemistrySettings | None] = ContextVar("chemistry_settings", default=None)


def load_settings() -> ChemistrySettings:
    """The frozen batch settings if a batch is running, else defaults + config file + environment."""
    if (frozen := active_settings.get()) is not None:
        return frozen
    load_dotenv()  # fills in from .env; variables already set in the shell win
    path = os.environ.get("MOLCURATOR_CHEM_CONFIG")
    values = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(values, dict):
        raise TypeError("chemistry configuration must be a JSON object")
    if os.environ.get("MOLCURATOR_QC_TIMEOUT_S"):
        values["timeout_s"] = float(os.environ["MOLCURATOR_QC_TIMEOUT_S"])
    return ChemistrySettings.model_validate(values)
