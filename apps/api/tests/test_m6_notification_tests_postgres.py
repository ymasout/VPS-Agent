import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.notification_tests as notification_tests
from app.config import Settings
from app.models import AlertEvent, NotificationTestRequest, Operation, OperationTransition
from app.notification_tests import create_notification_test

POSTGRES_URL = os.getenv("M6_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M6_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_m6_notification_test_idempotency_rate_limit_and_zero_operation_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(notification_tests, "session_factory", factory)
        fixed_time = datetime(2026, 7, 28, 15, 0, 30, tzinfo=timezone.utc)
        monkeypatch.setattr(notification_tests, "now_utc", lambda: fixed_time)
        sender = AsyncMock()
        monkeypatch.setattr(notification_tests, "send_dingtalk_payload", sender)
        settings = Settings(
            dingtalk_webhook_url="https://example.test/robot",
            notification_tests_enabled=True,
            notification_test_cooldown_seconds=60,
            skip_database_init=True,
        )
        first_key = uuid4()
        second_key = uuid4()
        concurrent_keys = [uuid4(), uuid4()]
        try:
            async with factory() as session:
                before = (
                    await session.scalar(select(func.count()).select_from(AlertEvent)),
                    await session.scalar(select(func.count()).select_from(Operation)),
                    await session.scalar(
                        select(func.count()).select_from(OperationTransition)
                    ),
                )
                background = BackgroundTasks()
                created = await create_notification_test(
                    background_tasks=background,
                    response=Response(status_code=202),
                    idempotency_key=first_key,
                    session=session,
                    settings=settings,
                )
            await background()

            async with factory() as session:
                stored = await session.get(NotificationTestRequest, created.id)
                assert stored is not None
                assert stored.status == "succeeded"
                assert stored.attempt_count == 1
                replay_background = BackgroundTasks()
                replay_response = Response(status_code=202)
                replay = await create_notification_test(
                    background_tasks=replay_background,
                    response=replay_response,
                    idempotency_key=first_key,
                    session=session,
                    settings=settings,
                )
                assert replay.id == created.id
                assert replay_response.status_code == 200
                assert replay_background.tasks == []

            async with factory() as session:
                with pytest.raises(HTTPException) as captured:
                    await create_notification_test(
                        background_tasks=BackgroundTasks(),
                        response=Response(status_code=202),
                        idempotency_key=second_key,
                        session=session,
                        settings=settings,
                    )
                assert captured.value.status_code == 429

            async with factory() as session:
                after = (
                    await session.scalar(select(func.count()).select_from(AlertEvent)),
                    await session.scalar(select(func.count()).select_from(Operation)),
                    await session.scalar(
                        select(func.count()).select_from(OperationTransition)
                    ),
                )
                assert after == before
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(NotificationTestRequest)
                        .where(
                            NotificationTestRequest.client_request_id == str(first_key)
                        )
                    )
                    == 1
                )
            sender.assert_awaited_once()

            monkeypatch.setattr(
                notification_tests,
                "now_utc",
                lambda: fixed_time.replace(minute=1),
            )

            async def create_concurrent(key: UUID) -> str:
                async with factory() as session:
                    try:
                        await create_notification_test(
                            background_tasks=BackgroundTasks(),
                            response=Response(status_code=202),
                            idempotency_key=key,
                            session=session,
                            settings=settings,
                        )
                    except HTTPException as error:
                        return f"error:{error.status_code}"
                    return "accepted"

            concurrent_results = await asyncio.gather(
                *(create_concurrent(key) for key in concurrent_keys)
            )
            assert sorted(concurrent_results) == ["accepted", "error:429"]
        finally:
            async with factory() as session:
                await session.execute(
                    delete(NotificationTestRequest).where(
                        NotificationTestRequest.client_request_id.in_(
                            [
                                str(first_key),
                                str(second_key),
                                *(str(key) for key in concurrent_keys),
                            ]
                        )
                    )
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
