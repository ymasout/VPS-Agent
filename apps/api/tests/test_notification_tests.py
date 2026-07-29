import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import app.notification_tests as notification_tests
from app.config import Settings
from app.main import app
from app.models import NotificationTestRequest
from app.notification_tests import (
    create_notification_test,
    create_notification_test_for_channel,
    deliver_notification_test,
    delivery_error_code,
    delivery_failure_status,
    maintain_notification_tests,
    rate_limit_window,
)
from app.notification_tests import (
    test_payload as build_test_payload,
)


class SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


def request(
    status: str = "pending",
    attempt_count: int = 0,
    channel: str = "dingtalk",
) -> NotificationTestRequest:
    now = datetime.now(timezone.utc)
    return NotificationTestRequest(
        id="11111111-1111-4111-8111-111111111111",
        organization_id="local",
        channel=channel,
        client_request_id="22222222-2222-4222-8222-222222222222",
        rate_limit_window=now.replace(second=0, microsecond=0),
        status=status,
        attempt_count=attempt_count,
        requested_by="local-admin",
        created_at=now,
        updated_at=now,
    )


def test_rate_limit_window_is_stable_and_payload_is_fixed() -> None:
    current = datetime(2026, 7, 28, 12, 1, 59, tzinfo=timezone.utc)
    assert rate_limit_window(current, 60) == datetime(
        2026, 7, 28, 12, 1, tzinfo=timezone.utc
    )
    payload = build_test_payload(request())
    serialized = str(payload)
    assert "管理员显式测试消息" in serialized
    assert "11111111-1111-4111-8111-111111111111" in serialized
    assert "access_token" not in serialized
    assert "webhook" not in serialized.lower()


def test_delivery_error_codes_do_not_preserve_remote_or_secret_text() -> None:
    rejected_error = RuntimeError("DingTalk rejected notification")
    assert delivery_error_code(rejected_error) == "notification_test_rejected"
    assert delivery_error_code(httpx.ReadTimeout("timeout")) == "notification_test_timeout"
    assert delivery_failure_status(rejected_error) == "failed"
    assert delivery_failure_status(httpx.ReadTimeout("timeout")) == "delivery_outcome_unknown"


def test_notification_test_is_sent_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    current = request()
    claim_session = AsyncMock()
    claim_session.scalar.return_value = current
    finish_session = AsyncMock()
    finish_session.scalar.return_value = current
    sessions = iter([claim_session, finish_session])
    sender = AsyncMock()
    monkeypatch.setattr(
        notification_tests,
        "session_factory",
        lambda: SessionContext(next(sessions)),
    )
    monkeypatch.setattr(notification_tests, "send_dingtalk_payload", sender)

    asyncio.run(
        deliver_notification_test(
            current.id,
            Settings(
                dingtalk_webhook_url="https://example.test/robot",
                notification_tests_enabled=True,
                skip_database_init=True,
            ),
        )
    )

    assert current.status == "succeeded"
    assert current.attempt_count == 1
    assert current.error_code is None
    sender.assert_awaited_once()
    assert claim_session.commit.await_count == 1
    assert finish_session.commit.await_count == 1

    second_session = AsyncMock()
    second_session.scalar.return_value = current
    monkeypatch.setattr(
        notification_tests,
        "session_factory",
        lambda: SessionContext(second_session),
    )
    asyncio.run(
        deliver_notification_test(
            current.id,
            Settings(
                dingtalk_webhook_url="https://example.test/robot",
                notification_tests_enabled=True,
                skip_database_init=True,
            ),
        )
    )
    sender.assert_awaited_once()


def test_telegram_notification_test_uses_same_at_most_once_audit_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = request(channel="telegram")
    claim_session = AsyncMock()
    claim_session.scalar.return_value = current
    finish_session = AsyncMock()
    finish_session.scalar.return_value = current
    sessions = iter([claim_session, finish_session])
    telegram_sender = AsyncMock()
    dingtalk_sender = AsyncMock()
    monkeypatch.setattr(
        notification_tests,
        "session_factory",
        lambda: SessionContext(next(sessions)),
    )
    monkeypatch.setattr(notification_tests, "send_telegram_payload", telegram_sender)
    monkeypatch.setattr(notification_tests, "send_dingtalk_payload", dingtalk_sender)

    asyncio.run(
        deliver_notification_test(
            current.id,
            Settings(
                telegram_bot_token="123456:token-value",
                telegram_chat_id="-100123",
                notification_tests_enabled=True,
                skip_database_init=True,
            ),
        )
    )

    assert current.status == "succeeded"
    assert current.attempt_count == 1
    telegram_sender.assert_awaited_once()
    dingtalk_sender.assert_not_awaited()
    payload = telegram_sender.await_args.args[1]
    assert payload["chat_id"] == "-100123"
    assert "管理员显式测试消息" in payload["text"]


@pytest.mark.parametrize(
    "settings",
    [
        Settings(
            notification_channels="telegram",
            notification_tests_enabled=True,
            telegram_bot_token=None,
            telegram_chat_id=None,
            skip_database_init=True,
        ),
        Settings(
            notification_channels="dingtalk",
            notification_tests_enabled=True,
            telegram_bot_token="123456:configured-but-disabled",
            telegram_chat_id="-100123",
            skip_database_init=True,
        ),
    ],
)
def test_create_telegram_test_requires_enabled_and_configured_channel(
    settings: Settings,
) -> None:
    session = AsyncMock()
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as captured:
        asyncio.run(
            create_notification_test_for_channel(
                "telegram",
                BackgroundTasks(),
                Response(status_code=202),
                UUID("99999999-9999-4999-8999-999999999999"),
                session,
                settings,
            )
        )

    assert captured.value.status_code == 409
    session.commit.assert_not_awaited()


def test_stale_sending_becomes_unknown_without_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = request(status="sending", attempt_count=1)
    stale.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    stale_result = MagicMock()
    stale_result.all.return_value = [stale]
    pending_result = MagicMock()
    pending_result.all.return_value = []
    stale_session = AsyncMock()
    stale_session.scalars.return_value = stale_result
    pending_session = AsyncMock()
    pending_session.scalars.return_value = pending_result
    sessions = iter([stale_session, pending_session])
    sender = AsyncMock()
    monkeypatch.setattr(
        notification_tests,
        "session_factory",
        lambda: SessionContext(next(sessions)),
    )
    monkeypatch.setattr(notification_tests, "send_dingtalk_payload", sender)

    asyncio.run(maintain_notification_tests(Settings(skip_database_init=True)))

    assert stale.status == "delivery_outcome_unknown"
    assert stale.error_code == "notification_test_delivery_outcome_unknown"
    sender.assert_not_awaited()


def test_disabled_maintenance_closes_pending_without_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = request()
    stale_result = MagicMock()
    stale_result.all.return_value = []
    pending_result = MagicMock()
    pending_result.all.return_value = [pending]
    stale_session = AsyncMock()
    stale_session.scalars.return_value = stale_result
    pending_session = AsyncMock()
    pending_session.scalars.return_value = pending_result
    sessions = iter([stale_session, pending_session])
    sender = AsyncMock()
    monkeypatch.setattr(
        notification_tests,
        "session_factory",
        lambda: SessionContext(next(sessions)),
    )
    monkeypatch.setattr(notification_tests, "send_dingtalk_payload", sender)

    asyncio.run(maintain_notification_tests(Settings(skip_database_init=True)))

    assert pending.status == "failed"
    assert pending.error_code == "notification_tests_disabled"
    assert pending.attempt_count == 0
    sender.assert_not_awaited()


def test_create_replays_same_idempotency_key_without_resending() -> None:
    existing = request(status="succeeded", attempt_count=1)
    session = AsyncMock()
    session.scalar.return_value = existing
    background = BackgroundTasks()
    response = Response(status_code=202)

    result = asyncio.run(
        create_notification_test(
            background_tasks=background,
            response=response,
            idempotency_key=UUID(existing.client_request_id),
            session=session,
            settings=Settings(
                dingtalk_webhook_url="https://example.test/robot",
                skip_database_init=True,
            ),
        )
    )

    assert result.id == existing.id
    assert response.status_code == 200
    assert background.tasks == []
    session.commit.assert_not_awaited()


def test_create_is_disabled_by_default() -> None:
    session = AsyncMock()
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as captured:
        asyncio.run(
            create_notification_test(
                background_tasks=BackgroundTasks(),
                response=Response(status_code=202),
                idempotency_key=UUID("44444444-4444-4444-8444-444444444444"),
                session=session,
                settings=Settings(
                    dingtalk_webhook_url="https://example.test/robot",
                    skip_database_init=True,
                ),
            )
        )

    assert captured.value.status_code == 403
    session.commit.assert_not_awaited()


def test_notification_test_api_rejects_request_body_before_delivery() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/notification-tests/dingtalk",
            headers={
                "X-Admin-Token": "change-me-in-production",
                "Idempotency-Key": "77777777-7777-4777-8777-777777777777",
            },
            json={},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "request body is not allowed"}


def test_create_persists_audit_before_scheduling_delivery() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.side_effect = [None, None]

    async def refresh(created: NotificationTestRequest) -> None:
        created.id = "55555555-5555-4555-8555-555555555555"

    session.refresh.side_effect = refresh
    background = BackgroundTasks()
    response = Response(status_code=202)

    result = asyncio.run(
        create_notification_test(
            background_tasks=background,
            response=response,
            idempotency_key=UUID("66666666-6666-4666-8666-666666666666"),
            session=session,
            settings=Settings(
                dingtalk_webhook_url="https://example.test/robot",
                notification_tests_enabled=True,
                skip_database_init=True,
            ),
        )
    )

    assert result.id == "55555555-5555-4555-8555-555555555555"
    assert result.status == "pending"
    assert result.attempt_count == 0
    session.commit.assert_awaited_once()
    assert len(background.tasks) == 1


def test_create_returns_rate_limit_after_concurrent_window_conflict() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.side_effect = [None, None, None, request()]
    session.commit.side_effect = IntegrityError("insert", {}, Exception("unique"))

    with pytest.raises(HTTPException) as captured:
        asyncio.run(
            create_notification_test(
                background_tasks=BackgroundTasks(),
                response=Response(status_code=202),
                idempotency_key=UUID("33333333-3333-4333-8333-333333333333"),
                session=session,
                settings=Settings(
                    dingtalk_webhook_url="https://example.test/robot",
                    notification_tests_enabled=True,
                    notification_test_cooldown_seconds=60,
                    skip_database_init=True,
                ),
            )
        )

    assert captured.value.status_code == 429
    assert captured.value.headers is not None
    assert int(captured.value.headers["Retry-After"]) >= 1


def test_create_does_not_mask_unrelated_integrity_errors_as_rate_limits() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.side_effect = [None, None, None, None]
    database_error = IntegrityError("insert", {}, Exception("unexpected"))
    session.commit.side_effect = database_error

    with pytest.raises(IntegrityError) as captured:
        asyncio.run(
            create_notification_test(
                background_tasks=BackgroundTasks(),
                response=Response(status_code=202),
                idempotency_key=UUID("88888888-8888-4888-8888-888888888888"),
                session=session,
                settings=Settings(
                    dingtalk_webhook_url="https://example.test/robot",
                    notification_tests_enabled=True,
                    skip_database_init=True,
                ),
            )
        )

    assert captured.value is database_error
