"""Server settings, read once at startup from environment variables (and the repo's .env file).

Variables already set in the environment win over values in .env.

| Variable                   | Default                        | Meaning                                   |
|----------------------------|--------------------------------|-------------------------------------------|
| MOLCURATOR_REPO            | two folders above app/server/  | MolCurator repository root (working dir)  |
| MOLCURATOR_RUNS_ROOT       | <repo>/data/runs               | where run folders are created             |
| MOLCURATOR_WEB_DIR         | <repo>/app/web                 | web app served at "/" (if the folder exists) |
| MOLCURATOR_API_TOKEN       | generated at startup           | token clients send as "Authorization: Bearer <token>" |
| MOLCURATOR_NO_AUTH         | 0                              | 1 = no token needed (only for a private machine) |
| MOLCURATOR_MAX_RUNS        | 1                              | how many agent runs may run at the same time |
| MOLCURATOR_CORS_ORIGINS    | *                              | comma-separated origins allowed to call the API |
| MOLCURATOR_REPO_URL        | https://github.com/varunrishi/molcurator | "Source code" link shown by the web app |
| MOLCURATOR_AGENT_CMD       | the `molcurator` command       | command that runs the agent (tests replace it) |
"""
import os
import secrets
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_REPO = Path(__file__).resolve().parents[2]  # app/server/settings.py -> repo root


@dataclass
class Settings:
    repo: Path
    runs_root: Path
    web_dir: Path
    api_token: str | None  # None = no authentication
    token_was_generated: bool
    max_runs: int
    cors_origins: list[str]
    repo_url: str
    agent_cmd: list[str]
    dotenv: dict[str, str] = field(default_factory=dict)  # the repo's .env, used to find xtb/orca/keys

    @property
    def api_dir(self) -> Path:
        """Bookkeeping for runs started by the API: one status file and one log per run."""
        return self.runs_root / ".api"

    def env_value(self, name: str) -> str | None:
        """A setting from the environment, else from the repo's .env (the same order the agent uses)."""
        return os.environ.get(name) or self.dotenv.get(name) or None


def default_agent_cmd() -> list[str]:
    """The `molcurator` command installed next to this Python, else the one on PATH."""
    beside_python = Path(sys.executable).with_name("molcurator")
    if beside_python.exists():
        return [str(beside_python)]
    found = shutil.which("molcurator")
    return [found] if found else [sys.executable, "-c", "from molcurator.cli import app; app()"]


def load_settings() -> Settings:
    repo = Path(os.environ.get("MOLCURATOR_REPO") or DEFAULT_REPO).resolve()
    dotenv = {k: v for k, v in dotenv_values(repo / ".env").items() if v} if (repo / ".env").is_file() else {}

    def get(name: str, default: str = "") -> str:
        return os.environ.get(name) or dotenv.get(name) or default

    no_auth = get("MOLCURATOR_NO_AUTH", "0") == "1"
    token = get("MOLCURATOR_API_TOKEN") or None
    generated = False
    if not token and not no_auth:
        token, generated = secrets.token_urlsafe(24), True  # printed once at startup (main.py)

    agent_cmd = shlex.split(get("MOLCURATOR_AGENT_CMD")) or default_agent_cmd()
    return Settings(
        repo=repo,
        runs_root=Path(get("MOLCURATOR_RUNS_ROOT") or repo / "data" / "runs").resolve(),
        web_dir=Path(get("MOLCURATOR_WEB_DIR") or repo / "app" / "web").resolve(),
        api_token=None if no_auth else token,
        token_was_generated=generated,
        max_runs=max(1, int(get("MOLCURATOR_MAX_RUNS", "1"))),
        cors_origins=[o.strip() for o in get("MOLCURATOR_CORS_ORIGINS", "*").split(",") if o.strip()],
        repo_url=get("MOLCURATOR_REPO_URL", "https://github.com/varunrishi/molcurator"),
        agent_cmd=agent_cmd,
        dotenv=dotenv,
    )
