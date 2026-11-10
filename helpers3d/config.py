"""Where keys, logs and settings live. Always outside the project folder, so nothing here can be committed."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional


def home_dir() -> Path:
    override = os.environ.get("H3D_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "3d-helper-scripts"


def load_config() -> dict:
    path = home_dir() / "config.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def tripo_key() -> Optional[str]:
    """The environment variable wins over the config file, so a shell can override a saved key."""
    return os.environ.get("TRIPO_API_KEY") or load_config().get("tripo_api_key") or None


def credit_log_path() -> Path:
    return home_dir() / "credits.jsonl"
