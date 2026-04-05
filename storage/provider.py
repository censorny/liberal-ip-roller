"""
Low-level configuration provider for Liberal IP Roller.
Handles Pydantic-based validation and persistent storage of app settings.

Architecture:
  AppConfig (global: language, theme, telegram, active_service)
  ├── yandex: YandexServiceConfig  (api + process — fully isolated)
  └── regru:  RegruServiceConfig   (api + process — fully isolated)
"""

import json
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
#  SHARED ENGINE CONFIG (base for both providers)
# ─────────────────────────────────────────────

class RollerConfig(BaseModel):
    """Common engine settings for the IP rotation process."""
    allowed_ranges: List[str] = []
    min_delay: float = 0.0
    max_delay: float = 0.0
    randomize_delay: bool = False
    dry_run: bool = False
    auto_start: bool = False
    log_limit: int = 100
    enable_notifications: bool = True
    error_wait_period: float = 30.0
    auto_restart_on_error: bool = True
    report_errors_to_tg: bool = False
    report_matches_to_tg: bool = True
    polling_delay: float = 1.0


# ─────────────────────────────────────────────
#  YANDEX CLOUD
# ─────────────────────────────────────────────

class YandexConfig(BaseModel):
    """Yandex Cloud API credentials and base settings."""
    iam_token: str = ""
    folder_id: str = ""
    sa_key_path: str = ""
    zone_id: str = "ru-central1-a"
    ip_limit: int = 2
    target_match_count: int = 1


class YandexRollerConfig(RollerConfig):
    """Yandex-specific roller settings with appropriate defaults."""
    allowed_ranges: List[str] = [
        "51.250.0.0/17",
        "84.201.128.0/18"
    ]
    polling_delay: float = 0.0


class YandexServiceConfig(BaseModel):
    """Aggregated Yandex service configuration."""
    api: YandexConfig = Field(default_factory=YandexConfig)
    process: YandexRollerConfig = Field(default_factory=YandexRollerConfig)


# ─────────────────────────────────────────────
#  REG.RU
# ─────────────────────────────────────────────

class RegruApiConfig(BaseModel):
    """Reg.ru CloudVPS API credentials and VM parameters."""
    api_token: str = ""
    api_base_url: str = "https://api.cloudvps.reg.ru/v1/reglets"
    region_slug: str = "openstack-msk1"
    server_size: str = "c1-m1-d10-hp"
    server_image: str = "ubuntu-18-04-amd64"
    ip_limit: int = 2


class RegruRollerConfig(RollerConfig):
    """Reg.ru specific roller settings synced with source/regru.py."""
    allowed_ranges: List[str] = [
        "79.174.91.0/24",
        "79.174.92.0/24",
        "79.174.93.0/24",
        "79.174.94.0/24",
        "79.174.95.0/24",
        "37.140.192.0/24",
        "89.108.126.0/24",
        "31.31.196.0/24",
        "89.111.170.0/24",
        "213.189.204.0/24"
    ]
    # Reference timings from source/regru.py
    initial_wait: float = 0.0         # No hard wait – start polling immediately
    check_interval: float = 10.0      # 10s intervals
    timeout_wait_time: float = 120.0  # 2m wait after timeout
    delete_wait_time: float = 90.0    # 1.5m wait after deletion
    check_interval: float = 5.0       # Interval between status checks
    stability_checks: int = 3         # N consecutive 'active+IP' checks to confirm stability
    delete_wait: float = 10.0         # Cooldown after deletion before next iteration
    vm_active_timeout: float = 240.0  # Maximum time to wait for VM to become active
    vm_delete_timeout: float = 180.0  # Maximum time to wait for VM deletion


class RegruServiceConfig(BaseModel):
    """Aggregated Reg.ru service configuration."""
    api: RegruApiConfig = Field(default_factory=RegruApiConfig)
    process: RegruRollerConfig = Field(default_factory=RegruRollerConfig)


# ─────────────────────────────────────────────
#  GLOBAL
# ─────────────────────────────────────────────

class ServiceConfig(BaseModel):
    """Base interface for all service configurations (for type hints)."""
    api: BaseModel = Field(default_factory=BaseModel)
    process: RollerConfig = Field(default_factory=RollerConfig)


class TelegramConfig(BaseModel):
    """Telegram notification settings (global, shared across providers)."""
    enabled: bool = False
    token: str = ""
    chat_ids: List[str] = []


class AppConfig(BaseModel):
    """Root configuration model for the entire application.
    
    Global fields (language, theme, telegram) are shared.
    Each provider (yandex, regru) has fully isolated api + process config.
    """
    # Provider-specific configs (fully isolated)
    yandex: YandexServiceConfig = Field(default_factory=YandexServiceConfig)
    regru: RegruServiceConfig = Field(default_factory=RegruServiceConfig)

    # Global settings
    language: str = "en"
    skip_language_selection: bool = False
    active_service: str = "yandex"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    debug: bool = False

    def get_service_config(self, name: Optional[str] = None):
        """
        Dynamically resolves the configuration for a service.
        Returns the typed sub-config for the active (or specified) provider.
        """
        svc_name = name or self.active_service
        config = getattr(self, svc_name, None)
        if config is None:
            return self.yandex
        return config


# ─────────────────────────────────────────────
#  CONFIG PROVIDER
# ─────────────────────────────────────────────

class ConfigProvider:
    """
    Persistent storage controller for the AppConfig.
    Handles loading from and saving to a JSON file.
    """
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            self.config = AppConfig()
            self.save()  # Bootstrap config on first run
        else:
            self.config = self.load()

    def load(self) -> AppConfig:
        """Loads configuration from disk. Returns safe defaults on any error."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return AppConfig(**data)
            except Exception:
                return AppConfig()
        return AppConfig()

    def save(self, config: Optional[AppConfig] = None):
        """Persists the current configuration state to disk."""
        if config:
            self.config = config
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(
                self.config.model_dump(),
                f,
                indent=4,
                ensure_ascii=False
            )
