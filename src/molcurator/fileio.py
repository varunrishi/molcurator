"""Small file helpers shared by the chemistry tools and the batch command: safe ids for
folder names, atomic JSON writes and long-path-safe paths on Windows."""
import json
import os
import re
import uuid
from pathlib import Path


def safe_id(candidate_id: str) -> str:
    """The id, if it is safe as a folder name (letters, digits, _ and -); else ValueError."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", candidate_id):
        raise ValueError("candidate id must contain only letters, digits, underscores or hyphens")
    return candidate_id


def native_path(path) -> Path:
    path = Path(path).resolve()
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        text = str(path)
        return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
    return path


def atomic_json(path, value) -> None:
    """Write JSON through a temporary file, so readers never see a half-written file."""
    path = native_path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)
