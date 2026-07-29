from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_agent_operation_route_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/agents/operations/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agent-operations"}


def test_system_info_is_managed_and_health_stays_minimal() -> None:
    with TestClient(app) as client:
        unauthenticated = client.get("/api/v1/system-info")
        response = client.get(
            "/api/v1/system-info", headers={"X-Admin-Token": "change-me-in-production"}
        )
        health = client.get("/healthz")

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "instance_id": "unset-instance",
        "version": "unset",
        "commit_sha": "unknown-build",
        "build_time": "unknown-build-time",
        "alembic_revision": [],
        "expected_alembic_revision": ["0019_m6_multichannel_notify"],
        "schema_current": False,
    }
    assert health.json() == {"status": "ok", "service": "api"}
