import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.dialects import postgresql

import app.api as api_module
from app.api import report_agent
from app.config import Settings
from app.models import Agent
from app.schemas import AgentReport, Metrics


def test_report_locks_agent_and_resolves_availability_before_heartbeat_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_seen = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)
    agent = Agent(
        id="agent-01",
        credential_hash="hash",
        name="test-vps",
        hostname="old-hostname",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.3.1",
        capabilities=[],
        last_seen_at=old_seen,
    )
    payload = AgentReport(
        hostname="new-hostname",
        version="0.3.1",
        capabilities=["docker"],
        collected_at=datetime.now(timezone.utc),
        metrics=Metrics(
            cpu_percent=10,
            memory_percent=20,
            memory_used_bytes=1,
            memory_total_bytes=2,
            disks=[],
        ),
        services=[],
        evidence_sources=[],
    )
    session = AsyncMock()
    session.scalar.return_value = agent
    rows = MagicMock()
    rows.all.return_value = []
    session.scalars.return_value = rows
    session.add = MagicMock()
    session.add_all = MagicMock()
    availability_last_seen: list[datetime | None] = []

    async def record_availability(*args: object, **kwargs: object) -> list[object]:
        availability_last_seen.append(args[1].last_seen_at)  # type: ignore[attr-defined]
        return []

    availability = AsyncMock(side_effect=record_availability)
    service_alerts = AsyncMock(return_value=[])
    reconcile = AsyncMock()
    monkeypatch.setattr(api_module, "evaluate_agent_availability", availability)
    monkeypatch.setattr(api_module, "evaluate_service_alerts", service_alerts)
    monkeypatch.setattr(api_module, "reconcile_service_instance_keys", reconcile)
    settings = Settings(dingtalk_webhook_url=None)

    asyncio.run(
        report_agent(payload, BackgroundTasks(), agent, session, settings)
    )

    locked_query = session.scalar.call_args_list[0].args[0]
    sql = str(locked_query.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    availability.assert_awaited_once()
    call = availability.await_args
    assert call.args[1] is agent
    assert call.kwargs["online"] is True
    assert availability_last_seen == [old_seen]
    assert agent.hostname == "new-hostname"
    assert agent.last_seen_at != old_seen
    session.commit.assert_awaited_once()
