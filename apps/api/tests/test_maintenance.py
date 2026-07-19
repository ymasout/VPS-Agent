import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

import app.maintenance as maintenance
from app.config import Settings
from app.maintenance import (
    control_plane_maintenance_loop,
    reconcile_offline_agents,
    run_maintenance_once,
)
from app.models import Agent


class SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


def test_offline_reconciler_evaluates_locked_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    agent = Agent(
        id="agent-01",
        credential_hash="hash",
        name="test-vps",
        hostname="vm-01",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.3.1",
        capabilities=[],
        last_seen_at=now - timedelta(minutes=2),
    )
    session = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = [agent]
    session.scalars.return_value = rows
    evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr(maintenance, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(maintenance, "evaluate_agent_availability", evaluate)
    settings = Settings(agent_offline_after_seconds=90)

    count = asyncio.run(reconcile_offline_agents(settings, current_time=now))

    assert count == 1
    query = session.scalars.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    evaluate.assert_awaited_once_with(
        session,
        agent,
        now,
        online=False,
        offline_after_seconds=90,
    )
    session.commit.assert_awaited_once()


def test_maintenance_still_delivers_notifications_when_scan_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = AsyncMock(side_effect=RuntimeError("database temporarily unavailable"))
    delivery = AsyncMock()
    log = MagicMock()
    log.aexception = AsyncMock()
    monkeypatch.setattr(maintenance, "reconcile_offline_agents", scan)
    monkeypatch.setattr(maintenance, "deliver_pending_notifications", delivery)
    monkeypatch.setattr(maintenance, "logger", log)
    settings = Settings()

    asyncio.run(run_maintenance_once(settings))

    delivery.assert_awaited_once_with(settings)
    log.aexception.assert_awaited_once_with("agent.availability_scan_failed")


def test_maintenance_retries_notifications_then_waits_startup_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = AsyncMock()
    sleeps: list[float] = []

    async def cancel_after_first_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(maintenance, "deliver_pending_notifications", delivery)
    monkeypatch.setattr(maintenance.asyncio, "sleep", cancel_after_first_sleep)
    settings = Settings(agent_offline_after_seconds=90)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(control_plane_maintenance_loop(settings))

    delivery.assert_awaited_once_with(settings)
    assert sleeps == [90]
