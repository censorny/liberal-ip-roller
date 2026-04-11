from __future__ import annotations

import json
from pathlib import Path

from app.paths import CONFIG_PATH

from .config_models import AppConfig


class ConfigProvider:
    """Persistent store for application configuration."""

    def __init__(self, config_path: str | Path = CONFIG_PATH):
        path = Path(config_path)
        if not path.is_absolute():
            path = CONFIG_PATH.parent / path

        self.config_path = path
        self.config = self.load() if self.config_path.exists() else AppConfig()

        if not self.config_path.exists():
            self.save()

    def load(self) -> AppConfig:
        """Load configuration from disk and fall back to defaults on invalid content."""
        if not self.config_path.exists():
            return AppConfig()

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return AppConfig(**data)
        except (OSError, ValueError, TypeError):
            return AppConfig()

    def save(self, config: AppConfig | None = None) -> None:
        """Persist the current configuration state."""
        if config is not None:
            self.config = config

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.config.model_dump(), indent=4, ensure_ascii=False),
            encoding="utf-8",
        )