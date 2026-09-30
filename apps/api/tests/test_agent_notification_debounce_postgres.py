"""Bounded real PostgreSQL interleavings; all external sends are replaced.

Use the existing M6_TEST_DATABASE_URL convention. Each scenario owns a random
schema containing only the three notification tables, never production data.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.maintenance as maintenance
import app.models as models
import app.notifications as notifications
from app.alerts import evaluate_agent_availability
from app.config import Settings
from app.models import Agent, AlertEvent, NotificationDelivery

POSTGRES_URL = os.getenv("M6_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set M6_TEST_DATABASE_URL")
NOW = datetime(2026, 9, 30, 4, tzinfo=timezone.utc)


async def bounded(awaitable):
    return await asyncio.wait_for(awaitable, timeout=10)


@asynccontextmanager
async def workspace(monkeypatch):
    schema = "debounce_" + uuid4().hex
    admin = create_async_engine(POSTGRES_URL)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(POSTGRES_URL, connect_args={"server_settings": {
        "search_path": schema, "application_name": schema,
        "lock_timeout": "5000", "statement_timeout": "8000",
    }})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tasks = []
    try:
        async with engine.begin() as conn:
            for model in (Agent, AlertEvent, NotificationDelivery):
                await conn.run_sync(model.__table__.create)
        async with factory() as session:
            session.add(Agent(
                id="agent", name="test", hostname="test", machine_id="test",
                credential_hash="test", os="test", arch="test", version="test",
                capabilities=[], last_seen_at=NOW - timedelta(seconds=180),
            ))
            await session.commit()

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        monkeypatch.setattr(notifications, "datetime", Clock)
        # ORM defaults/onupdate must share the worker clock, otherwise a frozen
        # future worker clock treats a brand-new sending lease as already stale.
        monkeypatch.setattr(models, "datetime", Clock)
        monkeypatch.setattr(notifications, "session_factory", factory)
        monkeypatch.setattr(maintenance, "session_factory", factory)
        settings = Settings(_env_file=None, notification_channels="dingtalk,telegram")
        sends = []

        async def sender(_settings, delivery, _event):
            sends.append((delivery.channel, delivery.notification_type))

        monkeypatch.setattr(notifications, "send_notification_delivery", sender)

        class Context:
            def start(self, awaitable):
                task = asyncio.create_task(awaitable)
                tasks.append(task)
                return task

            async def scan(self, at=NOW):
                return await maintenance.reconcile_offline_agents(settings, current_time=at)

            async def recover(self, session):
                # Same Agent -> event lock order as report_agent; no HTTP/background send.
                agent = await session.scalar(select(Agent).with_for_update())
                rows = await evaluate_agent_availability(
                    session, agent, NOW, online=True, offline_after_seconds=90,
                    notification_channels=settings.enabled_notification_channels,
                )
                agent.last_seen_at = NOW
                await session.flush()
                return [row.id for row in rows]

            async def rows(self):
                async with factory() as session:
                    return list((await session.scalars(select(NotificationDelivery))).all())

            async def deliver(self, identity):
                await notifications.deliver_notification(identity, settings)

            async def blocked(self):
                # Observe actual server lock contention before releasing the holder.
                async def observe():
                    async with admin.connect() as conn:
                        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                        while not await conn.scalar(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE application_name=:name AND "
                            "cardinality(pg_blocking_pids(pid)) > 0)"
                        ), {"name": schema}):
                            await asyncio.sleep(0.01)
                await asyncio.wait_for(observe(), timeout=3)

        yield Context(), factory, engine, sends
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def test_competing_scanners_skip_locked_and_survive_connection_restart(monkeypatch):
    async def scenario():
        async with workspace(monkeypatch) as (ctx, factory, engine, _):
            await ctx.scan(NOW - timedelta(seconds=89))  # 91 seconds: event only
            assert await ctx.rows() == []
            original = maintenance.evaluate_agent_availability
            entered, release = asyncio.Event(), asyncio.Event()

            async def held(*args, **kwargs):
                entered.set()
                await bounded(release.wait())
                return await original(*args, **kwargs)

            monkeypatch.setattr(maintenance, "evaluate_agent_availability", held)
            winner = ctx.start(ctx.scan())
            await bounded(entered.wait())
            assert await bounded(ctx.scan()) == 0
            release.set()
            assert await bounded(winner) == 1
            monkeypatch.setattr(maintenance, "evaluate_agent_availability", original)
            await engine.dispose()  # new connections, same durable database
            await bounded(asyncio.gather(ctx.scan(), ctx.scan(), ctx.scan()))
            rows = await ctx.rows()
            assert len(rows) == 2
            assert {(r.sequence, r.channel) for r in rows} == {(1, "dingtalk"), (1, "telegram")}
            async with factory() as session:
                events = list((await session.scalars(select(AlertEvent))).all())
                assert len(events) == 1 and events[0].notification_sequence == 1
    asyncio.run(bounded(scenario()))


@pytest.mark.parametrize("prior_failure", [False, True])
def test_recovery_holding_event_lock_suppresses_claim_or_retry(monkeypatch, prior_failure):
    async def scenario():
        async with workspace(monkeypatch) as (ctx, factory, engine, sends):
            await ctx.scan()
            firing = (await ctx.rows())[0]
            if prior_failure:
                async def timeout(*_):
                    raise httpx.ReadTimeout("synthetic")
                monkeypatch.setattr(notifications, "send_notification_delivery", timeout)
                await ctx.deliver(firing.id)

                async def record(_settings, delivery, _event):
                    sends.append((delivery.channel, delivery.notification_type))
                monkeypatch.setattr(notifications, "send_notification_delivery", record)

            async with factory() as session:
                recoveries = await ctx.recover(session)
                worker = ctx.start(ctx.deliver(firing.id))
                await ctx.blocked()
                assert not worker.done()
                await session.commit()
            await bounded(worker)
            await engine.dispose()
            await bounded(asyncio.gather(*(ctx.deliver(r.id) for r in await ctx.rows())))
            rows = await ctx.rows()
            assert len(rows) == 4 and len(recoveries) == 2
            stored = next(r for r in rows if r.id == firing.id)
            assert stored.status == "suppressed"
            assert stored.attempt_count == int(prior_failure)
            if prior_failure:
                assert stored.last_error == "notification_timeout"
                assert sends == [(firing.channel, "resolved")]
            else:
                assert sends == []
                assert all(r.status == "suppressed" and r.attempt_count == 0 for r in rows)
    asyncio.run(bounded(scenario()))


@pytest.mark.parametrize("channel", ["dingtalk", "telegram"])
@pytest.mark.parametrize("outcome", ["sent", "timeout", "rejected"])
def test_claim_before_recovery_and_inflight_result_cannot_restart_firing(
    monkeypatch, channel, outcome,
):
    async def scenario():
        async with workspace(monkeypatch) as (ctx, factory, engine, sends):
            await ctx.scan()
            firing = next(r for r in await ctx.rows() if r.channel == channel)
            entered, release = asyncio.Event(), asyncio.Event()

            async def held_sender(_settings, delivery, _event):
                sends.append((delivery.channel, delivery.notification_type))
                if delivery.notification_type == "firing":
                    entered.set()
                    await bounded(release.wait())
                    if outcome == "timeout":
                        raise httpx.ReadTimeout("synthetic")
                    if outcome == "rejected":
                        raise RuntimeError("synthetic")

            monkeypatch.setattr(notifications, "send_notification_delivery", held_sender)
            worker = ctx.start(ctx.deliver(firing.id))
            await bounded(entered.wait())  # sending/attempt is committed, network in flight
            await bounded(ctx.deliver(firing.id))  # competing worker cannot send again
            async with factory() as session:
                recoveries = await ctx.recover(session)
                await session.commit()
            await bounded(asyncio.gather(*(ctx.deliver(r) for r in recoveries)))
            assert sends == [(channel, "firing"), (channel, "resolved")]
            release.set()
            await bounded(worker)
            await engine.dispose()
            # Simulate fresh workers retrying after an in-flight failure has persisted.
            await bounded(asyncio.gather(*(ctx.deliver(r.id) for r in await ctx.rows())))
            rows = await ctx.rows()
            assert len(rows) == 4
            assert len({(r.event_id, r.sequence, r.channel) for r in rows}) == 4
            assert sends == [(channel, "firing"), (channel, "resolved")]
            assert all(r.status == "suppressed" and r.attempt_count == 0
                       for r in rows if r.channel != channel)
            stored = next(r for r in rows if r.id == firing.id)
            assert stored.attempt_count == 1
            assert stored.status == ("sent" if outcome == "sent" else "suppressed")
    asyncio.run(bounded(scenario()))


def test_fresh_process_uses_persisted_sequence_and_channel_attempts(monkeypatch):
    async def scenario():
        async with workspace(monkeypatch) as (ctx, factory, engine, sends):
            await ctx.scan()
            firing = next(r for r in await ctx.rows() if r.channel == "dingtalk")
            await ctx.deliver(firing.id)
            async with factory() as session:
                schema = await session.scalar(text("SELECT current_schema()"))
            await engine.dispose()
            # A fresh interpreter receives only database identity, no Python state.
            code = '''
import asyncio, os
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import app.maintenance as maintenance
import app.notifications as notifications
from app.alerts import evaluate_agent_availability
from app.config import Settings
from app.models import Agent, NotificationDelivery
async def main():
    schema = os.environ["DEBOUNCE_TEST_SCHEMA"]
    assert schema.startswith("debounce_") and len(schema) == 41
    engine = create_async_engine(os.environ["M6_TEST_DATABASE_URL"],
        connect_args={"server_settings": {"search_path": schema,
            "lock_timeout": "5000", "statement_timeout": "8000"}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    maintenance.session_factory = notifications.session_factory = factory
    sends = []
    async def sender(settings, delivery, event):
        sends.append((delivery.channel, delivery.notification_type))
    notifications.send_notification_delivery = sender
    settings = Settings(_env_file=None, notification_channels="dingtalk,telegram")
    now = datetime(2026, 9, 30, 4, tzinfo=timezone.utc)
    try:
        await maintenance.reconcile_offline_agents(settings, current_time=now)
        async with factory() as session:
            assert len(list((await session.scalars(select(NotificationDelivery))).all())) == 2
            agent = await session.scalar(select(Agent).with_for_update())
            await evaluate_agent_availability(session, agent, now,
                online=True, offline_after_seconds=90,
                notification_channels=settings.enabled_notification_channels)
            agent.last_seen_at = now
            await session.commit()
        async with factory() as session:
            ids = list((await session.scalars(select(NotificationDelivery.id))).all())
        for identity in ids:
            await notifications.deliver_notification(identity, settings)
        assert sends == [("dingtalk", "resolved")], sends
        print("FRESH_PROCESS_PERSISTENCE_PASSED")
    finally:
        await engine.dispose()
asyncio.run(main())
'''
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                env={**os.environ, "DEBOUNCE_TEST_SCHEMA": schema},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await bounded(process.communicate())
                assert process.returncode == 0, stderr.decode()
                assert b"FRESH_PROCESS_PERSISTENCE_PASSED" in stdout
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            rows = await ctx.rows()
            assert len(rows) == 4
            assert sends == [("dingtalk", "firing")]
            assert all(r.status == "sent" for r in rows if r.channel == "dingtalk")
            assert all(r.status == "suppressed" for r in rows if r.channel == "telegram")
    asyncio.run(bounded(scenario()))
