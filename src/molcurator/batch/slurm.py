"""Validated single-node SLURM scripts for batch runs; submission only on request."""
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator


def posix_absolute(value: str) -> str:
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
    orca_bin: str | None = None
    openmpi_home: str | None = None  # for orca_nprocs > 1 when Open MPI is not loaded as a module
    property: str = "homo_lumo_gap"
    predict_method: str | None = None
    orca: bool = Field(default=False, strict=True)
    orca_limit: int | None = Field(default=None, ge=0, strict=True)
    min_value: float | None = None
    max_value: float | None = None
    functional: str = "B3LYP"
    basis: str = "def2-SVP"
    resume: bool = Field(default=False, strict=True)
    plots: bool = Field(default=False, strict=True)

    @field_validator("project_dir", "input", "out", "chemistry_config", "orca_bin", "openmpi_home", "module_init")
    @classmethod
    def paths(cls, value):
        return posix_absolute(value) if value is not None else value

    @field_validator("job_name", "partition", "account", "qos")
    @classmethod
    def directives(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("SLURM names must contain only letters, numbers, dots, underscores or hyphens")
        return value

    @field_validator("property", "predict_method", "functional", "basis")
    @classmethod
    def keywords(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+*(),./-]*", value):
            raise ValueError("property, methods and basis must be single keyword tokens")
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


def render(config: SlurmSettings) -> str:
    # Paths in the configuration belong to the cluster, not the machine generating the script.
    lines = ["#!/usr/bin/env bash", f"#SBATCH --job-name={config.job_name}", "#SBATCH --nodes=1",
             "#SBATCH --ntasks=1", f"#SBATCH --cpus-per-task={config.cpus_per_task}",
             f"#SBATCH --mem={config.memory_mb}M", f"#SBATCH --time={config.time}",
             "#SBATCH --output=molcurator-%j.out"]
    lines += [f"#SBATCH --{option}={value}" for option in ("partition", "account", "qos")
              if (value := getattr(config, option))]
    lines += ["", "set -euo pipefail", "cd -- " + shlex.quote(config.project_dir)]
    if config.module_init:
        lines.append("source " + shlex.quote(config.module_init))
    if config.modules:
        lines.append("module load " + " ".join(shlex.quote(m) for m in config.modules))
    for key, value in (("MOLCURATOR_CHEM_CONFIG", config.chemistry_config), ("ORCA_BIN", config.orca_bin),
                       ("OPENMPI_HOME", config.openmpi_home)):
        if value is not None:
            lines.append(f"export {key}=" + shlex.quote(value))
    python = str(PurePosixPath(config.project_dir) / config.python)
    arguments = [python, "-m", "molcurator.batch.cli", "run", config.input, "--out", config.out,
                 "--property", config.property]
    if config.predict_method:
        arguments += ["--predict-method", config.predict_method]
    if config.orca:
        arguments.append("--orca")
    if config.orca_limit is not None:
        arguments += ["--orca-limit", str(config.orca_limit)]
    if config.min_value is not None:
        arguments += ["--min", str(config.min_value)]
    if config.max_value is not None:
        arguments += ["--max", str(config.max_value)]
    arguments += ["--functional", config.functional, "--basis", config.basis]
    if config.resume:
        arguments.append("--resume")
    if config.plots:
        arguments.append("--plots")
    lines += ["", "# A single sequential batch; ORCA uses the allocated CPUs (orca_nprocs).",
              shlex.join(arguments), ""]
    return "\n".join(lines)


def prepare(config_path, script_path, submit: bool = False) -> int:
    config = SlurmSettings.model_validate_json(Path(config_path).read_text(encoding="utf-8-sig"))
    script_path = Path(script_path).resolve()
    script_path.parent.mkdir(parents=True, exist_ok=True)
    with script_path.open("x", encoding="utf-8", newline="\n") as handle:  # never replace an existing job script
        handle.write(render(config))
    print(f"Generated: {script_path}")
    if not submit:
        print("Not submitted. Review the script, then run: sbatch " + shlex.quote(str(script_path)))
        return 0
    executable = shutil.which("sbatch")
    if executable is None:
        raise FileNotFoundError("sbatch not available; the script was generated but not submitted")
    result = subprocess.run([executable, "--parsable", str(script_path)], check=True, text=True,
                            capture_output=True)
    job_id = result.stdout.strip()
    if not re.fullmatch(r"\d+(?:;[A-Za-z0-9_.-]+)?", job_id):
        raise ValueError("unexpected sbatch response; inspect scheduler before resubmitting: " + job_id)
    receipt = {"job_id": job_id, "script": str(script_path), "config": config.model_dump()}
    script_path.with_suffix(script_path.suffix + ".submission.json").write_text(json.dumps(receipt, indent=2))
    print(f"Submitted job: {job_id}")
    return 0
