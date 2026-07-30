import re
from datetime import datetime, timezone
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .notification_catalog import NOTIFICATION_CHANNELS


class Settings(BaseSettings):
    app_name: str = "VPS Agent Control Plane"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vps_agent:vps_agent_dev@localhost:5432/vps_agent"
    redis_url: str = "redis://localhost:6379/0"
    admin_api_token: str = "change-me-in-production"
    control_plane_instance_id: str = "unset-instance"
    control_plane_version: str = "unset"
    control_plane_commit_sha: str = "unknown-build"
    control_plane_build_time: str = "unknown-build-time"
    principal_context_enabled: bool = False
    principal_read_authorization_enabled: bool = False
    principal_proxy_token: SecretStr | None = None
    principal_viewer_ids: str = ""
    dev_agent_registration_token: str | None = None
    agent_offline_after_seconds: int = Field(default=90, ge=30, le=3600)
    agent_availability_scan_interval_seconds: int = Field(default=30, ge=5, le=300)
    agent_release_repository: str = "ymasout/VPS-Agent"
    alert_pending_observations: int = 2
    dingtalk_webhook_url: str | None = None
    dingtalk_secret: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    notification_channels: str = "dingtalk"
    console_public_url: str = "http://localhost:3000"
    notification_timeout_seconds: float = 5.0
    notification_sending_stale_seconds: int = 120
    notification_tests_enabled: bool = False
    notification_test_cooldown_seconds: int = Field(default=60, ge=30, le=3600)
    diagnostic_provider: str = "deterministic"
    diagnostic_api_url: str | None = None
    diagnostic_api_key: str | None = None
    diagnostic_model: str = "ops-diagnostic"
    diagnostic_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    diagnostic_max_context_bytes: int = Field(default=131072, ge=16384, le=262144)
    diagnostic_log_lookback_seconds: int = Field(default=900, ge=60, le=86400)
    diagnostic_max_log_lines: int = Field(default=200, ge=1, le=500)
    diagnostic_max_log_bytes: int = Field(default=65536, ge=1024, le=65536)
    diagnostic_collection_timeout_seconds: int = Field(default=10, ge=1, le=15)
    diagnostic_request_claim_seconds: int = Field(default=60, ge=30, le=600)
    diagnostic_run_stale_seconds: int = Field(default=300, ge=60, le=3600)
    conversation_provider: str = "deterministic"
    conversation_api_url: str | None = None
    conversation_api_key: str | None = None
    conversation_model: str = "ops-conversation"
    conversation_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    conversation_turn_stale_seconds: int = Field(default=300, ge=60, le=3600)
    conversation_max_context_bytes: int = Field(default=131072, ge=16384, le=262144)
    conversation_repository_knowledge_enabled: bool = False
    conversation_repository_chat_enabled: bool = False
    conversation_context_chat_enabled: bool = False
    conversation_fleet_chat_enabled: bool = False
    conversation_insights_enabled: bool = False
    conversation_review_enabled: bool = False
    conversation_repository_max_context_bytes: int = Field(
        default=24576, ge=4096, le=65536
    )
    conversation_repository_max_results: int = Field(default=8, ge=1, le=16)
    conversation_repository_max_terms: int = Field(default=8, ge=1, le=16)
    conversation_repository_max_excerpt_bytes: int = Field(
        default=2048, ge=256, le=4096
    )
    conversation_repository_stale_seconds: int = Field(
        default=86400, ge=300, le=2592000
    )
    conversation_operation_handoff_enabled: bool = False
    conversation_operation_timeline_enabled: bool = False
    operation_signing_key_id: str = ""
    operation_signing_private_key_base64: str = ""
    operation_observation_max_age_seconds: int = Field(default=120, ge=30, le=600)
    operation_claim_lease_seconds: int = Field(default=60, ge=30, le=300)
    operation_execution_timeout_seconds: int = Field(default=30, ge=5, le=120)
    operation_deploy_execution_timeout_seconds: int = Field(default=300, ge=30, le=900)
    operation_execution_result_grace_seconds: int = Field(default=15, ge=5, le=60)
    operation_verification_window_seconds: int = Field(default=30, ge=0, le=300)
    operation_verification_timeout_seconds: int = Field(default=180, ge=30, le=900)
    operation_max_output_bytes: int = Field(default=16384, ge=1024, le=65536)
    operation_max_output_lines: int = Field(default=100, ge=1, le=500)
    github_app_id: str | None = None
    github_app_private_key_base64: str | None = None
    github_app_installation_id: int | None = Field(default=None, gt=0)
    github_app_slug: str | None = None
    github_webhook_secret: str | None = None
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_allowed_file_paths: str = "README.md,docker-compose.yml,compose.yaml"
    github_max_file_bytes: int = Field(default=65536, ge=1024, le=65536)
    github_webhook_max_bytes: int = Field(default=1048576, ge=1024, le=1048576)
    github_sync_concurrency: int = Field(default=4, ge=1, le=8)
    github_webhook_rate_limit_per_minute: int = Field(default=120, ge=0, le=10000)
    skip_database_init: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("notification_channels", mode="before")
    @classmethod
    def validate_notification_channels(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("notification channels must be a comma-separated string")
        channels = [item.strip().lower() for item in value.split(",") if item.strip()]
        if not channels:
            raise ValueError("at least one notification channel must be enabled")
        if len(set(channels)) != len(channels):
            raise ValueError("notification channels must not contain duplicates")
        unknown = [channel for channel in channels if channel not in NOTIFICATION_CHANNELS]
        if unknown:
            raise ValueError(f"unsupported notification channel: {unknown[0]}")
        reserved = [
            channel for channel in channels if not NOTIFICATION_CHANNELS[channel].implemented
        ]
        if reserved:
            raise ValueError(
                f"notification channel is reserved but not implemented: {reserved[0]}"
            )
        return ",".join(channels)

    @property
    def enabled_notification_channels(self) -> tuple[str, ...]:
        return tuple(self.notification_channels.split(","))

    @field_validator(
        "principal_proxy_token",
        "github_app_id",
        "github_app_private_key_base64",
        "github_app_installation_id",
        "github_app_slug",
        "github_webhook_secret",
        mode="before",
    )
    @classmethod
    def empty_optional_secret_values_are_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("principal_viewer_ids", mode="before")
    @classmethod
    def validate_principal_viewer_ids(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("principal viewer ids must be a comma-separated string")
        viewer_ids = [item.strip() for item in value.split(",") if item.strip()]
        if len(set(viewer_ids)) != len(viewer_ids):
            raise ValueError("principal viewer ids must not contain duplicates")
        invalid = [
            viewer_id
            for viewer_id in viewer_ids
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}", viewer_id)
        ]
        if invalid:
            raise ValueError("principal viewer id is invalid")
        return ",".join(viewer_ids)

    @property
    def principal_viewers(self) -> tuple[str, ...]:
        return tuple(item for item in self.principal_viewer_ids.split(",") if item)

    @model_validator(mode="after")
    def validate_diagnostic_timing(self) -> "Settings":
        if self.principal_read_authorization_enabled and not self.principal_context_enabled:
            raise ValueError("principal read authorization requires principal context")
        if self.principal_context_enabled:
            token = (
                self.principal_proxy_token.get_secret_value()
                if self.principal_proxy_token is not None
                else ""
            )
            if len(token) < 32 or token.lower().startswith(("replace_", "change-me")):
                raise ValueError("principal proxy token must be a non-placeholder secret")
            if not self.principal_viewers:
                raise ValueError("at least one principal viewer id is required")
        if self.app_env == "production":
            if self.control_plane_instance_id == "unset-instance" or (
                self.control_plane_instance_id.startswith("replace_")
            ):
                raise ValueError("production control-plane instance id must be set")
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
                self.control_plane_instance_id,
            ):
                raise ValueError("production control-plane instance id is invalid")
            if self.control_plane_version == "unset" or self.control_plane_version.startswith(
                "replace_"
            ):
                raise ValueError("production control-plane version must be set")
            if not re.fullmatch(r"[0-9a-f]{40}", self.control_plane_commit_sha):
                raise ValueError("production control-plane commit sha must be set")
            try:
                parsed_build_time = datetime.fromisoformat(
                    self.control_plane_build_time.replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ValueError(
                    "production control-plane build time must be an ISO-8601 timestamp"
                ) from error
            if (
                parsed_build_time.tzinfo is None
                or parsed_build_time.utcoffset() != timezone.utc.utcoffset(None)
            ):
                raise ValueError("production control-plane build time must be UTC")
            if self.control_plane_build_time == "unknown-build-time":
                raise ValueError("production control-plane build time must be set")
        if self.diagnostic_provider not in {"deterministic", "http_json"}:
            raise ValueError("unsupported diagnostic provider")
        if self.diagnostic_provider == "http_json" and not self.diagnostic_api_url:
            raise ValueError("diagnostic API URL is required for http_json provider")
        if self.conversation_provider not in {"deterministic", "http_json"}:
            raise ValueError("unsupported conversation provider")
        if self.conversation_provider == "http_json" and not self.conversation_api_url:
            raise ValueError(
                "conversation API URL is required for http_json provider"
            )
        if self.diagnostic_run_stale_seconds <= self.diagnostic_timeout_seconds:
            raise ValueError("diagnostic run stale threshold must exceed provider timeout")
        if self.conversation_turn_stale_seconds <= self.conversation_timeout_seconds:
            raise ValueError("conversation turn stale threshold must exceed provider timeout")
        if (
            self.conversation_repository_max_context_bytes
            > self.conversation_max_context_bytes
        ):
            raise ValueError(
                "conversation repository context budget must not exceed total context budget"
            )
        if self.agent_availability_scan_interval_seconds > self.agent_offline_after_seconds:
            raise ValueError("agent availability scan interval must not exceed offline threshold")
        if bool(self.operation_signing_key_id) != bool(self.operation_signing_private_key_base64):
            raise ValueError("operation signing key id and private key must be set together")
        if (
            self.operation_verification_timeout_seconds
            <= self.operation_verification_window_seconds
        ):
            raise ValueError("operation verification timeout must exceed stability window")
        github_values = (
            self.github_app_id,
            self.github_app_private_key_base64,
            self.github_app_installation_id,
            self.github_webhook_secret,
        )
        if any(value is not None for value in github_values) and not all(
            value is not None for value in github_values
        ):
            raise ValueError(
                "GitHub App id, private key, installation id and webhook secret "
                "must be set together"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
