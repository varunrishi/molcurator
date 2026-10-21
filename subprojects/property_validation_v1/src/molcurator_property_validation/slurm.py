"""Generate validated single-node SLURM scripts; submission is explicit."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess

from pydantic import BaseModel, ConfigDict, Field, field_validator


def posix_absolute(value):
    if not PurePosixPath(value).is_absolute() or any(c in value for c in ("\n", "\r", "\x00")):
        raise ValueError("cluster paths must be absolute POSIX paths without control characters")
    return value


class SlurmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    project_dir: str
    input: str
    out: str
    python: str = ".venv/bin/python"
    job_name: str = "molcurator-properties"
    partition: str | None = None
    account: str | None = None
    qos: str | None = None
    cpus_per_task: int = Field(default=1, ge=1, strict=True)
    memory_mb: int = Field(default=4096, ge=1, strict=True)
    time: str = "01:00:00"
    modules: list[str] = Field(default_factory=list)
    module_init: str | None = None
    chemistry_config: str | None = None
    xtb_bin: str | None = None
    orca_bin: str | None = None
    orca: bool = Field(default=False, strict=True)
    orca_limit: int | None = Field(default=None, ge=0, strict=True)
    min_gap: float | None = None
    max_gap: float | None = None
    functional: str = "B3LYP"
    basis: str = "def2-SVP"
    resume: bool = Field(default=False, strict=True)
    plots: bool = Field(default=False, strict=True)

    @field_validator("project_dir", "input", "out", "chemistry_config", "xtb_bin", "orca_bin", "module_init")
    @classmethod
    def paths(cls, value):
        return posix_absolute(value) if value is not None else value

    @field_validator("job_name", "partition", "account", "qos")
    @classmethod
    def directives(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("SLURM names must contain only letters, numbers, dots, underscores or hyphens")
        return value

    @field_validator("time")
    @classmethod
    def walltime(cls, value):
        if not re.fullmatch(r"(?:\d+-)?\d{1,3}:[0-5]\d:[0-5]\d", value):
            raise ValueError("time must be HH:MM:SS or D-HH:MM:SS")
        return value

    @field_validator("modules")
    @classmethod
    def module_names(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./+-]*", value) for value in values):
            raise ValueError("invalid module name")
        return values

    @field_validator("python")
    @classmethod
    def python_path(cls, value):
        if not value or any(c in value for c in ("\n", "\r", "\x00")):
            raise ValueError("python must be an executable path")
        return value


def render(config):
    # Paths in the configuration belong to the cluster, not the generation host.
    lines = ["#!/usr/bin/env bash", f"#SBATCH --job-name={config.job_name}",
             "#SBATCH --nodes=1", "#SBATCH --ntasks=1",
             f"#SBATCH --cpus-per-task={config.cpus_per_task}",
             f"#SBATCH --mem={config.memory_mb}M", f"#SBATCH --time={config.time}",
             "#SBATCH --output=molcurator-%j.out"]
    for option in ("partition", "account", "qos"):
        value = getattr(config, option)
        if value:
            lines.append(f"#SBATCH --{option}={value}")
    lines += ["", "set -euo pipefail", "cd -- " + shlex.quote(config.project_dir)]
    if config.module_init:
        lines.append("source " + shlex.quote(config.module_init))
    if config.modules:
        lines.append("module load " + " ".join(shlex.quote(m) for m in config.modules))
    for key, value in (("MOLCURATOR_CHEM_CONFIG", config.chemistry_config),
                       ("XTB_BIN", config.xtb_bin), ("ORCA_BIN", config.orca_bin)):
        if value is not None:
            lines.append(f"export {key}=" + shlex.quote(value))
    python = str(PurePosixPath(config.project_dir) / config.python)
    arguments = [python, "-m", "molcurator_property_validation.batch", "run", config.input, "--out", config.out]
    if config.orca:
        arguments.append("--orca")
    if config.orca_limit is not None:
        arguments += ["--orca-limit", str(config.orca_limit)]
    if config.min_gap is not None:
        arguments += ["--min-gap", str(config.min_gap)]
    if config.max_gap is not None:
        arguments += ["--max-gap", str(config.max_gap)]
    arguments += ["--functional", config.functional, "--basis", config.basis]
    if config.resume:
        arguments.append("--resume")
    if config.plots:
        arguments.append("--plots")
    lines += ["", "# A single sequential batch; ORCA PAL uses the allocated CPUs.",
              shlex.join(arguments), ""]
    return "\n".join(lines)


def prepare(config_path, script_path, submit=False):
    config = SlurmSettings.model_validate_json(Path(config_path).read_text(encoding="utf-8-sig"))
    script_path = Path(script_path).resolve()
    script_path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse accidental replacement of an existing job definition.
    with script_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(render(config))
    print(f"Generated: {script_path}")
    if submit:
        executable = shutil.which("sbatch")
        if executable is None:
            raise FileNotFoundError("sbatch not available; the script was generated but not submitted")
        result = subprocess.run([executable, "--parsable", str(script_path)], check=True,
                                text=True, capture_output=True)
        job_id = result.stdout.strip()
        if not re.fullmatch(r"\d+(?:;[A-Za-z0-9_.-]+)?", job_id):
            raise ValueError("unexpected sbatch response; inspect scheduler before resubmitting: " + job_id)
        receipt = dict(job_id=job_id, script=str(script_path), config=config.model_dump())
        script_path.with_suffix(script_path.suffix + ".submission.json").write_text(json.dumps(receipt, indent=2))
        print(f"Submitted job: {job_id}")
    else:
        print("Not submitted. Review the script, then run: sbatch " + shlex.quote(str(script_path)))
    return 0
