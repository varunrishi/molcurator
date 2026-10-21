"""Atomic JSON and platform paths without chemistry or plotting dependencies."""
import json
import os
from pathlib import Path
import uuid


def native_path(path):
    path = Path(path).resolve()
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        text = str(path)
        return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
    return path


def atomic_json(path, value):
    path = native_path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)
