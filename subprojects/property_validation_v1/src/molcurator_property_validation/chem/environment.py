"""Read only chemistry executable settings from .env without overriding process settings."""
import os
from pathlib import Path


def load_binary_environment(path=None):
    path = Path(path) if path is not None else Path.cwd() / '.env'
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or key not in ('XTB_BIN', 'ORCA_BIN', 'MOLCURATOR_QC_TIMEOUT_S', 'MOLCURATOR_CHEM_CONFIG'):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if value and not os.environ.get(key):
            os.environ[key] = value
