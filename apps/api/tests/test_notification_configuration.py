from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def configured_settings() -> Settings:
    return Settings(
        dingtalk_webhook_url=(
            "https://oapi.dingtalk.com/robot/send?access_token=must-not-leak"
        ),
        dingtalk_secret="must-not-leak-secret",
        console_public_url="https://ops.example.com",
        skip_database_init=True,
    )


def test_notification_configuration_is_managed_and_secret_free() -> None:
    app.dependency_overrides[get_settings] = configured_settings
    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/api/v1/notification-configuration")
            response = client.get(
                "/api/v1/notification-configuration",
                headers={"X-Admin-Token": "change-me-in-production"},
            )
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    serialized = response.text
    assert payload["ready"] is True
    assert payload["channels"] == [
        {
            "channel": "dingtalk",
            "configured": True,
            "signing_enabled": True,
            "supports": ["firing", "resolved"],
        }
    ]
    assert len(payload["templates"]) == 4
    assert payload["max_delivery_attempts"] == 3
    assert "must-not-leak" not in serialized
    assert "access_token" not in serialized


def test_notification_configuration_reports_missing_webhook() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        dingtalk_webhook_url=None,
        dingtalk_secret=None,
        skip_database_init=True,
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/notification-configuration",
                headers={"X-Admin-Token": "change-me-in-production"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["issues"] == ["dingtalk_webhook_missing"]


def test_production_notification_configuration_requires_https_console_links() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        admin_api_token="test-admin-token",
        control_plane_instance_id="test-instance",
        control_plane_version="0.6.3-dev",
        control_plane_commit_sha="a" * 40,
        control_plane_build_time="2026-07-28T00:00:00Z",
        dingtalk_webhook_url="https://example.test/robot",
        console_public_url="http://ops.example.com",
        skip_database_init=True,
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/notification-configuration",
                headers={"X-Admin-Token": "test-admin-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["issues"] == ["console_public_url_not_https"]
