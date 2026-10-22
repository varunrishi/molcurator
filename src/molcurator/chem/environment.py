"""Read only chemistry executable settings from .env without overriding process settings."""
import os
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

KEYS = ("XTB_BIN", "ORCA_BIN", "MOLCURATOR_QC_TIMEOUT_S", "MOLCURATOR_CHEM_CONFIG")  # nothing else, e.g. no API keys
# The checkout's own .env (src/molcurator/chem/ -> repository root), where scripts/setup.sh writes XTB_BIN
REPO_ENV = Path(__file__).resolve().parents[3] / ".env"


def load_binary_environment(path=None):
    """Set the chemistry variables in KEYS from a .env file, never overriding one already set.

    Without a path: the nearest .env at or above the working directory (as python-dotenv finds it),
    else the repository's, so a run started elsewhere (e.g. a notebook) still finds XTB_BIN.
    """
    if path is None:
        path = find_dotenv(usecwd=True) or REPO_ENV
    if not Path(path).is_file():
        return
    for key, value in dotenv_values(path).items():
        if key in KEYS and value and not os.environ.get(key):
            os.environ[key] = value
