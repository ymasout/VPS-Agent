import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.notification_tests as notification_test_module
import app.notifications as notifications
from app.alerts import notification_deliveries
from app.config import Settings
from app.models import (
    Agent,
    AlertEvent,
    NotificationDelivery,
    NotificationTestRequest,
    Operation,
    OperationTransition,
)
from app.notification_tests import create_notification_test_for_channel
from app.notifications import deliver_notification

POSTGRES_URL = os.getenv("M6_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M6_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_multichannel_delivery_is_independent_and_preserves_zero_operation_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(notifications, "session_factory", factory)
        monkeypatch.setattr(notification_test_module, "session_factory", factory)
        event_id = str(uuid4())
        test_request_key = uuid4()
        current_time = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        sender = AsyncMock()

        async def send_by_channel(
            settings: Settings,
            delivery: NotificationDelivery,
            event: AlertEvent,
        ) -> None:
            assert settings.enabled_notification_channels == ("dingtalk", "telegram")
            assert event.id == event_id
            assert delivery.render_context["title"] == "Frozen alert title"
            if delivery.channel == "dingtalk":
                raise RuntimeError("DingTalk rejected notification")

        sender.side_effect = send_by_channel
        monkeypatch.setattr(notifications, "send_notification_delivery", sender)
        settings = Settings(
            notification_channels="dingtalk,telegram",
            dingtalk_webhook_url="https://example.test/robot",
            telegram_bot_token="123456:token-value",
            telegram_chat_id="-100123",
            notification_tests_enabled=True,
            skip_database_init=True,
        )
        try:
            async with factory() as session:
                operation_counts_before = (
                    await session.scalar(select(func.count()).select_from(Operation)),
                    await session.scalar(
                        select(func.count()).select_from(OperationTransition)
                    ),
                )
                event = AlertEvent(
                    id=event_id,
                    agent_id=await session.scalar(select(Agent.id).limit(1)),
                    fingerprint=f"m6-multichannel-{event_id}",
                    source="service",
                    service_kind="systemd",
                    service_key="api.service",
                    title="Frozen alert title",
                    severity="critical",
                    status="firing",
                    observation_count=1,
                    notification_channels=["dingtalk", "telegram"],
                    detail="Frozen alert detail",
                    first_observed_at=current_time,
                    last_observed_at=current_time,
                    firing_at=current_time,
                )
                if event.agent_id is None:
                    pytest.skip("isolated PostgreSQL fixture has no agent")
                session.add(event)
                await session.flush()
                deliveries = notification_deliveries(
                    event, "firing", settings.enabled_notification_channels
                )
                session.add_all(deliveries)
                event.title = "Mutated after delivery creation"
                await session.commit()
                delivery_ids = {item.channel: item.id for item in deliveries}

            await asyncio.gather(
                *(
                    deliver_notification(delivery_id, settings)
                    for delivery_id in delivery_ids.values()
                )
            )

            async with factory() as session:
                stored = {
                    item.channel: item
                    for item in (
                        await session.scalars(
                            select(NotificationDelivery).where(
                                NotificationDelivery.event_id == event_id
                            )
                        )
                    ).all()
                }
                assert set(stored) == {"dingtalk", "telegram"}
                assert {item.sequence for item in stored.values()} == {1}
                assert stored["dingtalk"].status == "failed"
                assert stored["dingtalk"].last_error == "notification_rejected"
                assert stored["telegram"].status == "sent"
                assert stored["telegram"].last_error is None
                assert all(item.attempt_count == 1 for item in stored.values())
                assert all(
                    item.render_context["title"] == "Frozen alert title"
                    for item in stored.values()
                )
                operation_counts_after = (
                    await session.scalar(select(func.count()).select_from(Operation)),
                    await session.scalar(
                        select(func.count()).select_from(OperationTransition)
                    ),
                )
                assert operation_counts_after == operation_counts_before
            assert sender.await_count == 2

            telegram_test_sender = AsyncMock()
            monkeypatch.setattr(
                notification_test_module,
                "send_telegram_payload",
                telegram_test_sender,
            )
            async with factory() as session:
                background = BackgroundTasks()
                created_test = await create_notification_test_for_channel(
                    "telegram",
                    background,
                    Response(status_code=202),
                    test_request_key,
                    session,
                    settings,
                )
            await background()
            async with factory() as session:
                stored_test = await session.get(NotificationTestRequest, created_test.id)
                assert stored_test is not None
                assert stored_test.channel == "telegram"
                assert stored_test.status == "succeeded"
                assert stored_test.attempt_count == 1
            telegram_test_sender.assert_awaited_once()
        finally:
            async with factory() as session:
                await session.execute(
                    delete(NotificationTestRequest).where(
                        NotificationTestRequest.client_request_id
                        == str(test_request_key)
                    )
                )
                await session.execute(delete(AlertEvent).where(AlertEvent.id == event_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
