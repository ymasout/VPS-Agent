from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VPS Agent Control Plane"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vps_agent:vps_agent_dev@localhost:5432/vps_agent"
    redis_url: str = "redis://localhost:6379/0"
    admin_api_token: str = "change-me-in-production"
    dev_agent_registration_token: str | None = None
    agent_offline_after_seconds: int = 90
    agent_release_repository: str = "ymasout/VPS-Agent"
    alert_pending_observations: int = 2
    dingtalk_webhook_url: str | None = None
    dingtalk_secret: str | None = None
    console_public_url: str = "http://localhost:3000"
    notification_timeout_seconds: float = 5.0
    notification_sending_stale_seconds: int = 120
    diagnostic_provider: str = "deterministic"
    diagnostic_api_url: str | None = None
    diagnostic_api_key: str | None = None
    diagnostic_model: str = "ops-diagnostic"
    diagnostic_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    diagnostic_log_lookback_seconds: int = Field(default=900, ge=60, le=86400)
    diagnostic_max_log_lines: int = Field(default=200, ge=1, le=500)
    diagnostic_max_log_bytes: int = Field(default=65536, ge=1024, le=65536)
    diagnostic_collection_timeout_seconds: int = Field(default=10, ge=1, le=15)
    diagnostic_request_claim_seconds: int = Field(default=60, ge=30, le=600)
    diagnostic_run_stale_seconds: int = Field(default=300, ge=60, le=3600)
    skip_database_init: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_diagnostic_timing(self) -> "Settings":
        if self.diagnostic_run_stale_seconds <= self.diagnostic_timeout_seconds:
            raise ValueError("diagnostic run stale threshold must exceed provider timeout")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
