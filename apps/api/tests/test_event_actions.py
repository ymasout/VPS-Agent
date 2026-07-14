import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import act_on_event
from app.models import AlertEvent
from app.schemas import AlertEventAction


def event(status: str = "firing") -> AlertEvent:
    now = datetime.now(timezone.utc)
    return AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint="fingerprint",
        active_key=None if status == "resolved" else "fingerprint",
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status=status,
        observation_count=2,
        first_observed_at=now,
        last_observed_at=now,
        firing_at=now,
        resolved_at=now if status == "resolved" else None,
    )


def test_event_can_be_acknowledged() -> None:
    current = event()
    session = AsyncMock()
    session.get.return_value = current

    result = asyncio.run(
        act_on_event("event-01", AlertEventAction(action="acknowledge"), session)
    )

    assert current.status == "acknowledged"
    assert current.acknowledged_at is not None
    assert result.status == "acknowledged"
    session.commit.assert_awaited_once()


def test_event_can_be_silenced_for_bounded_duration() -> None:
    current = event()
    session = AsyncMock()
    session.get.return_value = current

    result = asyncio.run(
        act_on_event(
            "event-01",
            AlertEventAction(action="silence", silence_minutes=30),
            session,
        )
    )

    assert current.status == "silenced"
    assert current.silenced_until is not None
    assert result.silenced_until == current.silenced_until


def test_resolved_event_cannot_be_changed() -> None:
    session = AsyncMock()
    session.get.return_value = event("resolved")

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            act_on_event("event-01", AlertEventAction(action="acknowledge"), session)
        )

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()
