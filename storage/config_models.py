from __future__ import annotations

from pydantic import BaseModel, Field

from .defaults import load_selectel_default_ranges


class RollerConfig(BaseModel):
    """Common engine settings shared by all providers."""

    allowed_ranges: list[str] = Field(default_factory=list)
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


class YandexApiConfig(BaseModel):
    iam_token: str = ""
    folder_id: str = ""
    sa_key_path: str = ""
    zone_id: str = "ru-central1-a"
    ip_limit: int = 2
    target_match_count: int = 1


class YandexRollerConfig(RollerConfig):
    allowed_ranges: list[str] = Field(
        default_factory=lambda: ["51.250.0.0/17", "84.201.128.0/18"]
    )
    polling_delay: float = 0.0


class YandexServiceConfig(BaseModel):
    api: YandexApiConfig = Field(default_factory=YandexApiConfig)
    process: YandexRollerConfig = Field(default_factory=YandexRollerConfig)


class RegruApiConfig(BaseModel):
    api_token: str = ""
    api_base_url: str = "https://api.cloudvps.reg.ru/v1/reglets"
    region_slug: str = "openstack-msk1"
    server_size: str = "c2-m2-d10-base"
    server_image: str = "ubuntu-18-04-amd64"
    ip_limit: int = 2
    target_match_count: int = 1


class RegruRollerConfig(RollerConfig):
    allowed_ranges: list[str] = Field(
        default_factory=lambda: [
            "79.174.91.0/24",
            "79.174.92.0/24",
            "79.174.93.0/24",
            "79.174.94.0/24",
            "79.174.95.0/24",
            "37.140.192.0/24",
            "31.31.196.0/24",
            "213.189.204.0/24",
            "31.31.197.0/24",
            "31.31.198.0/24",
            "37.140.193.0/24",
            "37.140.194.0/24",
            "37.140.195.0/24",
        ]
    )
    initial_wait: float = 90.0
    check_interval: float = 5.0
    timeout_wait_time: float = 120.0
    delete_wait_time: float = 90.0
    stability_checks: int = 3
    delete_wait: float = 10.0
    vm_active_timeout: float = 240.0
    vm_delete_timeout: float = 180.0


class RegruServiceConfig(BaseModel):
    api: RegruApiConfig = Field(default_factory=RegruApiConfig)
    process: RegruRollerConfig = Field(default_factory=RegruRollerConfig)


class SelectelApiConfig(BaseModel):
    username: str = ""
    password: str = ""
    account_id: str = ""
    project_name: str = ""
    server_id_ru2: str = ""
    server_id_ru3: str = ""
    ip_limit: int = 2
    target_match_count: int = 1


class SelectelRollerConfig(RollerConfig):
    allowed_ranges: list[str] = Field(default_factory=load_selectel_default_ranges)
    association_timeout: float = 15.0


class SelectelServiceConfig(BaseModel):
    api: SelectelApiConfig = Field(default_factory=SelectelApiConfig)
    process: SelectelRollerConfig = Field(default_factory=SelectelRollerConfig)


class ServiceConfig(BaseModel):
    api: BaseModel = Field(default_factory=BaseModel)
    process: RollerConfig = Field(default_factory=RollerConfig)


class TelegramConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    chat_ids: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Root application configuration."""

    yandex: YandexServiceConfig = Field(default_factory=YandexServiceConfig)
    regru: RegruServiceConfig = Field(default_factory=RegruServiceConfig)
    selectel: SelectelServiceConfig = Field(default_factory=SelectelServiceConfig)

    language: str = "ru"
    skip_language_selection: bool = False
    active_service: str = "yandex"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    debug: bool = False

    def get_service_config(
        self,
        name: str | None = None,
    ) -> YandexServiceConfig | RegruServiceConfig | SelectelServiceConfig:
        service_name = name or self.active_service
        return getattr(self, service_name, self.yandex)