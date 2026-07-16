import asyncio
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import app.notifications as notifications
from app.config import Settings
from app.models import AlertEvent, NotificationDelivery
from app.notifications import (
    deliver_notification,
    deliver_pending_notifications,
    dingtalk_payload,
    send_dingtalk_notification,
    signed_dingtalk_webhook,
)


class SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


def event() -> AlertEvent:
    now = datetime.now(timezone.utc)
    return AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint="fingerprint",
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="test-vps: API [prod] 异常",
        severity="critical",
        status="firing",
        observation_count=2,
        detail="failed *without* leaking markdown",
        first_observed_at=now,
        last_observed_at=now,
    )


def test_dingtalk_signature_preserves_webhook_token() -> None:
    timestamp = 1710000000000
    url = signed_dingtalk_webhook(
        "https://oapi.dingtalk.com/robot/send?access_token=token-value",
        "secret-value",
        timestamp,
    )
    query = parse_qs(urlsplit(url).query)
    expected = base64.b64encode(
        hmac.new(
            b"secret-value",
            f"{timestamp}\nsecret-value".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()

    assert query["access_token"] == ["token-value"]
    assert query["timestamp"] == [str(timestamp)]
    assert query["sign"] == [expected]


def test_dingtalk_markdown_escapes_untrusted_service_text() -> None:
    payload = dingtalk_payload(event(), "firing", "https://ops.example.com/")
    text = payload["markdown"]["text"]  # type: ignore[index]

    assert "\\[prod\\]" in text
    assert "\\*without\\*" in text
    assert "https://ops.example.com/events/event-01" in text


def test_dingtalk_sender_accepts_success_and_rejects_api_error() -> None:
    requests: list[httpx.Request] = []

    def success(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    settings = Settings(
        dingtalk_webhook_url="https://oapi.dingtalk.com/robot/send?access_token=token",
        dingtalk_secret="secret",
        skip_database_init=True,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(success))
    asyncio.run(send_dingtalk_notification(settings, event(), "firing", client))
    asyncio.run(client.aclose())

    assert len(requests) == 1
    assert requests[0].url.params.get("timestamp") is not None

    async def rejected() -> None:
        error_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"errcode": 310000, "errmsg": "keywords not in content"},
                )
            )
        )
        try:
            with pytest.raises(RuntimeError, match="DingTalk rejected"):
                await send_dingtalk_notification(settings, event(), "firing", error_client)
        finally:
            await error_client.aclose()

    asyncio.run(rejected())


def test_stale_sending_delivery_is_reclaimed_and_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    delivery = NotificationDelivery(
        id="delivery-01",
        event_id="event-01",
        notification_type="firing",
        sequence=1,
        channel="dingtalk",
        status="sending",
        attempt_count=1,
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=3),
    )
    session = AsyncMock()
    session.scalar.return_value = delivery
    session.get.return_value = event()
    sender = AsyncMock()
    monkeypatch.setattr(notifications, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(notifications, "send_dingtalk_notification", sender)
    settings = Settings(
        dingtalk_webhook_url="https://example.test/robot",
        notification_sending_stale_seconds=120,
        skip_database_init=True,
    )

    asyncio.run(deliver_notification("delivery-01", settings))

    assert delivery.status == "sent"
    assert delivery.attempt_count == 2
    assert session.commit.await_count == 2
    sender.assert_awaited_once()


def test_fresh_sending_delivery_is_not_reclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    delivery = NotificationDelivery(
        id="delivery-01",
        event_id="event-01",
        notification_type="firing",
        sequence=1,
        channel="dingtalk",
        status="sending",
        attempt_count=1,
        created_at=now - timedelta(minutes=1),
        updated_at=now,
    )
    session = AsyncMock()
    session.scalar.return_value = delivery
    sender = AsyncMock()
    monkeypatch.setattr(notifications, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(notifications, "send_dingtalk_notification", sender)
    settings = Settings(
        dingtalk_webhook_url="https://example.test/robot",
        notification_sending_stale_seconds=120,
        skip_database_init=True,
    )

    asyncio.run(deliver_notification("delivery-01", settings))

    assert delivery.status == "sending"
    assert delivery.attempt_count == 1
    session.commit.assert_not_awaited()
    sender.assert_not_awaited()


def test_pending_scan_includes_stale_sending_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scalar_result = MagicMock()
    scalar_result.all.return_value = ["delivery-01"]
    session = AsyncMock()
    session.scalars.return_value = scalar_result
    worker = AsyncMock()
    monkeypatch.setattr(notifications, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(notifications, "deliver_notification", worker)
    settings = Settings(
        dingtalk_webhook_url="https://example.test/robot",
        notification_sending_stale_seconds=120,
        skip_database_init=True,
    )

    asyncio.run(deliver_pending_notifications(settings))

    query = str(session.scalars.await_args.args[0])
    assert "notification_deliveries.status =" in query
    assert "notification_deliveries.updated_at <=" in query
    worker.assert_awaited_once_with("delivery-01", settings)
