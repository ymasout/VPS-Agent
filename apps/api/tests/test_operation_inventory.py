"""Exercise real keyset SQL and HTTP validation on an isolated in-memory database."""

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import get_session
from app.models import Operation
from app.operation_inventory import router

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
PROXY = "test-read-" + "a" * 40


@pytest.fixture
def workspace():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Operation.__table__.create(engine)
    with Session(engine) as session:
        for i in range(5):
            session.add(
                Operation(
                    id=f"op-{i}",
                    agent_id=f"agent-{i % 2}",
                    instance_id="instance-1",
                    action_type="docker_compose_deploy" if i == 4 else "docker_restart",
                    rollback_of="op-0" if i == 4 else None,
                    status="failed" if i == 4 else "awaiting_confirmation",
                    requested_by="requester",
                    confirmed_by="approver" if i == 4 else None,
                    risk_level="medium",
                    impact_summary="token=private-value",
                    plan_snapshot={
                        "machine": {"name": "web-01"},
                        "service": {"name": "api", "environment": "production"},
                        "secret": "must-not-appear",
                    },
                    precheck_result={"passed": True},
                    verification_policy={},
                    idempotency_key=f"key-{i}",
                    task_signature="private-signature",
                    output="private-output",
                    expires_at=NOW + timedelta(minutes=5),
                    requested_at=NOW,
                    completed_at=None,
                )
            )
        session.commit()

        class ReadSession:
            async def scalar(self, query):
                return session.scalar(query)

            async def scalars(self, query):
                return session.scalars(query)

        statements = []

        @event.listens_for(engine, "before_cursor_execute")
        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_session] = lambda: ReadSession()
        app.dependency_overrides[get_settings] = lambda: Settings(skip_database_init=True)
        with TestClient(app) as client:
            yield client, app, statements
    engine.dispose()


def test_pages_are_stable_bounded_and_do_not_expose_snapshots_or_write(workspace):
    client, _, statements = workspace
    seen = []
    cursor = None
    for _ in range(3):
        response = client.get(
            "/api/v1/operations",
            params={
                "limit": 2,
                **({"cursor": cursor} if cursor else {}),
            },
        )
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 5
        assert len(page["items"]) <= 2
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        for secret in (
            "must-not-appear",
            "private-value",
            "private-output",
            "private-signature",
            "plan_snapshot",
            "task_signature",
            "idempotency_key",
        ):
            assert secret not in response.text
    assert seen == ["op-4", "op-3", "op-2", "op-1", "op-0"]
    assert cursor is None
    assert all(statement.lstrip().startswith("SELECT") for statement in statements)


def test_filters_apply_in_sql_and_cursor_cannot_cross_filters(workspace):
    client, _, _ = workspace
    response = client.get(
        "/api/v1/operations",
        params={
            "status": "failed",
            "action_type": "docker_compose_deploy",
            "agent_id": "agent-0",
            "requested_by": "requester",
            "confirmed_by": "approver",
            "since": "2026-09-08T11:00:00Z",
            "until": "2026-09-08T13:00:00Z",
        },
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["op-4"]
    assert response.json()["items"][0]["rollback_of"] == "op-0"
    for field in ("status", "action_type", "agent_id", "requested_by", "confirmed_by"):
        assert client.get("/api/v1/operations", params={field: "unknown"}).json()["total"] == 0
    first = client.get("/api/v1/operations?limit=1").json()
    assert (
        client.get(
            "/api/v1/operations",
            params={
                "cursor": first["next_cursor"],
                "status": "failed",
            },
        ).status_code
        == 422
    )
    assert client.get("/api/v1/operations?since=2026-09-09").json()["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "cursor=invalid",
        "cursor=W10",
        "cursor=bnVsbA",
        "since=invalid",
        "since=2026-09-09&until=2026-09-08",
        "agent_id=" + "x" * 37,
    ],
)
def test_invalid_inputs_fail_closed(workspace, query):
    client, _, _ = workspace
    assert client.get("/api/v1/operations?" + query).status_code == 422


@pytest.mark.parametrize("field", ["since", "until", "cursor"])
@pytest.mark.parametrize("value", [
    "0001-01-01T00:00:00+01:00",
    "9999-12-31T23:59:59-01:00",
])
def test_utc_overflow_is_rejected_before_sql(workspace, field, value):
    client, _, statements = workspace
    if field == "cursor":
        cursor = client.get("/api/v1/operations?limit=1").json()["next_cursor"]
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        payload[2] = value
        value = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    statements.clear()
    response = client.get("/api/v1/operations", params={field: value})
    assert response.status_code == 422
    assert response.json() == {"detail": (
        "invalid operation cursor" if field == "cursor" else "invalid operation time range"
    )}
    assert statements == []


@pytest.mark.parametrize("value", ["2026-09-08T20:00:00+08:00", "2026-09-08T12:00:00"])
def test_cursor_and_filters_normalize_equivalent_times(workspace, value):
    client, _, _ = workspace
    first = client.get("/api/v1/operations", params={"since": value, "limit": 1}).json()
    cursor = first["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    payload[2] = value
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    response = client.get("/api/v1/operations", params={
        "since": "2026-09-08T12:00:00Z", "cursor": cursor,
    })
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["op-3", "op-2", "op-1", "op-0"]


@pytest.mark.parametrize("user,code", [("viewer", 403), ("operator", 200), ("approver", 200)])
def test_named_roles_use_existing_operation_read_capability(workspace, user, code):
    client, app, _ = workspace
    settings = Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_read_authorization_enabled=True,
        principal_proxy_token=PROXY,
        principal_viewer_ids="viewer,operator,approver",
        principal_write_context_enabled=True,
        principal_write_authorization_enabled=True,
        principal_write_proxy_token="write-" + "b" * 40,
        principal_role_bindings_json=json.dumps(
            [
                {
                    "auth_source": "caddy_basic",
                    "auth_subject": role,
                    "principal_id": f"local:00000000-0000-4000-8000-00000000000{i}",
                    "display_name": role,
                    "roles": [role],
                }
                for i, role in enumerate(("operator", "approver"))
            ]
        ),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {
        "X-VPS-Agent-Principal-Id": user,
        "X-VPS-Agent-Principal-Source": "caddy_basic",
        "X-VPS-Agent-Principal-Proxy-Token": PROXY,
    }
    assert client.get("/api/v1/operations", headers=headers).status_code == code
    assert client.get("/api/v1/operations").status_code == 401
    assert (
        client.get(
            "/api/v1/operations", headers={"X-Admin-Token": "change-me-in-production"}
        ).status_code
        == 401
    )
    headers["X-VPS-Agent-Principal-Proxy-Token"] = "forged"
    assert client.get("/api/v1/operations", headers=headers).status_code == 401
