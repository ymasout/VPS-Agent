import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api import list_events
from app.models import Agent, AlertEvent, ManagedService, ServiceInstance


def event(identifier: str, *, status: str, observed_at: datetime) -> AlertEvent:
    return AlertEvent(
        id=identifier,
        organization_id="local",
        agent_id="agent-1",
        source="service",
        service_kind="docker",
        service_key="api-key",
        title="API health check failed",
        severity="critical",
        status=status,
        observation_count=3,
        detail="bounded detail",
        first_observed_at=observed_at - timedelta(minutes=5),
        last_observed_at=observed_at,
        firing_at=observed_at,
    )


def invoke(session, **overrides):
    arguments = {
        "event_status": None,
        "severity": None,
        "agent_id": None,
        "service_id": None,
        "since": None,
        "until": None,
        "q": None,
        "cursor": None,
        "limit": 50,
        "session": session,
    }
    arguments.update(overrides)
    return asyncio.run(list_events(**arguments))


def test_event_inventory_is_bounded_active_first_and_uses_safe_display_fields() -> None:
    now = datetime(2026, 9, 2, 8, tzinfo=timezone.utc)
    agent = Agent(id="agent-1", organization_id="local", name="web-01")
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="api-key",
    )
    managed = ManagedService(
        id="service-1",
        organization_id="local",
        name="payments-api",
        environment="production",
        criticality="critical",
    )
    rows = MagicMock()
    rows.all.return_value = [
        (event("event-active", status="firing", observed_at=now), agent, instance, managed),
        (
            event("event-resolved", status="resolved", observed_at=now - timedelta(hours=1)),
            agent,
            instance,
            managed,
        ),
    ]
    session = MagicMock()
    session.scalar = AsyncMock(return_value=2)
    session.execute = AsyncMock(return_value=rows)

    page = invoke(
        session,
        event_status="firing",
        severity="critical",
        agent_id="agent-1",
        service_id="service-1",
        since=now - timedelta(days=1),
        until=now,
        q="api",
        limit=1,
    )

    assert page.total == 2
    assert page.next_cursor is not None
    assert len(page.items) == 1
    assert page.items[0].agent_name == "web-01"
    assert page.items[0].service_id == "service-1"
    assert page.items[0].service_name == "payments-api"
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "alert_events.status = 'firing'" in sql
    assert "alert_events.severity = 'critical'" in sql
    assert "service_instances.service_id = 'service-1'" in sql
    assert "CASE WHEN (alert_events.status = 'resolved') THEN 1 ELSE 0 END" in sql
    assert "LIMIT 2" in sql


def test_event_cursor_is_bound_to_original_filter_set() -> None:
    now = datetime(2026, 9, 2, 8, tzinfo=timezone.utc)
    agent = Agent(id="agent-1", organization_id="local", name="web-01")
    rows = MagicMock()
    rows.all.return_value = [
        (event("event-1", status="firing", observed_at=now), agent, None, None),
        (
            event("event-0", status="firing", observed_at=now - timedelta(minutes=1)),
            agent,
            None,
            None,
        ),
    ]
    session = MagicMock()
    session.scalar = AsyncMock(return_value=2)
    session.execute = AsyncMock(return_value=rows)
    first = invoke(session, severity="critical", limit=1)

    with pytest.raises(HTTPException) as error:
        invoke(session, severity="warning", cursor=first.next_cursor, limit=1)

    assert error.value.status_code == 422
    assert error.value.detail == "invalid event cursor"
