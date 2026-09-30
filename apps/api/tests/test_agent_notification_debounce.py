"""Real persisted state across scans/workers; SQLite does not prove PG locking."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.notifications as notifications
from app.alerts import agent_offline_notification_due, evaluate_agent_availability
from app.api import agent_is_online
from app.config import Settings
from app.models import Agent, AlertEvent, NotificationDelivery

BASE = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


@pytest.fixture
def workspace(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (Agent, AlertEvent, NotificationDelivery):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add(Agent(
            id="agent-1", name="test", hostname="test", machine_id="test",
            credential_hash="test", os="test", arch="test", version="test",
            capabilities=[], last_seen_at=BASE,
        ))
        session.commit()

    clock = [BASE]
    locks = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    class AsyncSessionAdapter:
        async def __aenter__(self):
            self.session = Session(engine, expire_on_commit=False)
            return self

        async def __aexit__(self, *_):
            self.session.close()

        async def scalar(self, query):
            return self.session.scalar(query)

        async def get(self, model, identity, **kwargs):
            if model is AlertEvent:
                locks.append(kwargs.get("with_for_update"))
            return self.session.get(model, identity, **kwargs)

        async def flush(self):
            self.session.flush()

        async def commit(self):
            self.session.commit()

        def add(self, row):
            self.session.add(row)

        def add_all(self, rows):
            self.session.add_all(rows)

    sender = AsyncMock()
    monkeypatch.setattr(notifications, "session_factory", AsyncSessionAdapter)
    monkeypatch.setattr(notifications, "datetime", Clock)
    monkeypatch.setattr(notifications, "send_notification_delivery", sender)

    def observe(seconds, online=False, channels=("dingtalk",), notification_after=180):
        clock[0] = BASE + timedelta(seconds=seconds)

        async def action():
            async with AsyncSessionAdapter() as session:
                agent = await session.get(Agent, "agent-1")
                deliveries = await evaluate_agent_availability(
                    session, agent, clock[0], online=online,
                    offline_after_seconds=90, notification_channels=channels,
                    notification_after_seconds=notification_after,
                )
                if online:
                    agent.last_seen_at = clock[0]
                await session.commit()
                return [row.id for row in deliveries]

        return asyncio.run(action())

    def deliver(identity, after=180):
        asyncio.run(notifications.deliver_notification(identity, Settings(
            _env_file=None, agent_offline_notification_after_seconds=after,
        )))

    yield engine, clock, observe, deliver, sender, locks
    engine.dispose()


def test_notification_setting_does_not_relax_online_safety():
    settings = Settings(_env_file=None)
    assert settings.agent_offline_after_seconds == 90
    assert settings.agent_offline_notification_after_seconds == 180
    now = BASE + timedelta(seconds=120)
    assert not agent_is_online(BASE, now, settings.agent_offline_after_seconds)
    assert not agent_offline_notification_due(BASE, now, 180)
    for invalid in (0, -1, 86401):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, agent_offline_notification_after_seconds=invalid)


@pytest.mark.parametrize("seconds,due", [(179.999, False), (180, True), (181, True)])
def test_exact_boundary_uses_server_receipt(seconds, due):
    assert agent_offline_notification_due(BASE, BASE + timedelta(seconds=seconds), 180) is due
    assert not agent_offline_notification_due(None, BASE, 180)


def test_short_outage_still_records_event_but_no_notifications(workspace):
    engine, _, observe, _, sender, _ = workspace
    assert observe(91) == []
    assert observe(179) == []
    with Session(engine) as session:
        event = session.scalar(select(AlertEvent))
        assert event.status == "firing"
        assert event.notification_sequence == 0
    assert observe(179.5, online=True) == []
    with Session(engine) as session:
        event = session.scalar(select(AlertEvent))
        assert event.status == "resolved"
        assert event.active_key is None
        assert session.scalar(select(NotificationDelivery)) is None
    sender.assert_not_awaited()


def test_later_scan_after_restart_enqueues_once_at_180(workspace):
    engine, _, observe, _, _, _ = workspace
    assert observe(91) == []
    assert observe(179) == []
    assert len(observe(180)) == 1
    assert observe(210) == []
    with Session(engine) as session:
        event = session.scalar(select(AlertEvent))
        assert event.firing_at.replace(tzinfo=timezone.utc) == BASE + timedelta(seconds=91)
        assert event.notification_sequence == 1
        delivery = session.scalar(select(NotificationDelivery))
        assert delivery.attempt_count == 0
        assert delivery.render_context["detail"].endswith(BASE.replace(tzinfo=None).isoformat())


def test_long_outage_sends_then_pairs_recovery(workspace):
    engine, _, observe, deliver, sender, locks = workspace
    firing, = observe(180)
    deliver(firing)
    resolved, = observe(210, online=True)
    deliver(resolved)
    deliver(resolved)
    assert sender.await_count == 2
    assert all(locks)
    with Session(engine) as session:
        rows = session.scalars(select(NotificationDelivery)).all()
        assert {row.notification_type for row in rows} == {"firing", "resolved"}
        assert all(row.status == "sent" and row.attempt_count == 1 for row in rows)


@pytest.mark.parametrize("recovery_first", [False, True])
def test_recovery_before_worker_suppresses_both_regardless_of_order(workspace, recovery_first):
    engine, _, observe, deliver, sender, _ = workspace
    firing, = observe(180)
    resolved, = observe(181, online=True)
    for identity in ([resolved, firing] if recovery_first else [firing, resolved]):
        deliver(identity)
    deliver(firing)
    sender.assert_not_awaited()
    with Session(engine) as session:
        rows = session.scalars(select(NotificationDelivery)).all()
        assert all(row.status == "suppressed" and row.attempt_count == 0 for row in rows)


def test_uncertain_firing_stops_stale_retry_but_allows_recovery(workspace):
    engine, _, observe, deliver, sender, _ = workspace
    sender.side_effect = httpx.ReadTimeout("secret-must-not-leak")
    firing, = observe(180)
    deliver(firing)
    resolved, = observe(181, online=True)
    sender.side_effect = None
    deliver(firing)
    deliver(resolved)
    assert sender.await_count == 2
    with Session(engine) as session:
        failed = session.get(NotificationDelivery, firing)
        assert failed.status == "suppressed"
        assert failed.attempt_count == 1
        assert failed.last_error == "notification_timeout"
        assert session.get(NotificationDelivery, resolved).status == "sent"


def test_recovery_is_paired_per_channel_not_per_event(workspace):
    engine, _, observe, deliver, sender, _ = workspace
    first, second = observe(180, channels=("dingtalk", "telegram"))
    deliver(first)
    recoveries = observe(181, online=True)
    deliver(second)
    for identity in recoveries:
        deliver(identity)
    assert sender.await_count == 2
    with Session(engine) as session:
        rows = session.scalars(select(NotificationDelivery)).all()
        assert all(row.status == "sent" for row in rows if row.channel == "dingtalk")
        assert all(row.status == "suppressed" for row in rows if row.channel == "telegram")


def test_legacy_queued_firing_respects_new_threshold(workspace):
    engine, clock, observe, deliver, sender, _ = workspace
    firing, = observe(100, notification_after=90)
    deliver(firing)
    sender.assert_not_awaited()
    with Session(engine) as session:
        row = session.get(NotificationDelivery, firing)
        assert row.status == "pending" and row.attempt_count == 0
    clock[0] = BASE + timedelta(seconds=180)
    deliver(firing)
    sender.assert_awaited_once()


def test_custom_threshold_and_new_outage_get_fresh_wait(workspace):
    _, _, observe, deliver, sender, _ = workspace
    assert observe(180, notification_after=240) == []
    firing, = observe(240, notification_after=240)
    deliver(firing, after=240)
    recovery, = observe(250, online=True)
    deliver(recovery)
    assert observe(341) == []
    assert observe(429) == []
    second_firing, = observe(430)
    assert second_firing != firing
    assert sender.await_count == 2


@pytest.mark.parametrize("status", ["silenced", "acknowledged"])
def test_acknowledgement_or_active_silence_does_not_start_delayed_firing(workspace, status):
    engine, _, observe, _, _, _ = workspace
    observe(91)
    with Session(engine) as session:
        event = session.scalar(select(AlertEvent))
        event.status = status
        event.silenced_until = BASE + timedelta(seconds=300) if status == "silenced" else None
        session.commit()
    assert observe(180) == []
    assert observe(181, online=True) == []


def test_expired_agent_silence_refires_only_once(workspace):
    engine, _, observe, deliver, sender, _ = workspace
    firing, = observe(180)
    deliver(firing)
    with Session(engine) as session:
        event = session.scalar(select(AlertEvent))
        event.status = "silenced"
        event.silenced_until = BASE + timedelta(seconds=240)
        session.commit()
    assert observe(239) == []
    refiring, = observe(240)
    deliver(refiring)
    assert observe(270) == []
    assert sender.await_count == 2


def test_event_lock_is_requested_when_worker_decides_delivery(workspace):
    _, _, observe, deliver, _, locks = workspace
    firing, = observe(180)
    deliver(firing)
    assert locks == [True]
