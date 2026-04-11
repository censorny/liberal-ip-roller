from __future__ import annotations

import json
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
VERSION_PATH = PROJECT_ROOT / "version.json"
TEMP_DIR = PROJECT_ROOT / "temp"


def load_version(default: str = "0.0.0") -> str:
    """Read the application version from version.json."""
    try:
        data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default

    return str(data.get("version", default))