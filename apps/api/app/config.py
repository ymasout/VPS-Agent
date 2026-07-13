from functools import lru_cache

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
    skip_database_init: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
