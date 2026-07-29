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
from app.notification_catalog import (
    IMPLEMENTED_NOTIFICATION_CHANNELS,
    NOTIFICATION_CHANNELS,
)
from app.notifications import (
    NOTIFICATION_DELIVERY_ADAPTERS,
    deliver_notification,
    deliver_pending_notifications,
    dingtalk_payload,
    notification_delivery_error_code,
    send_dingtalk_notification,
    send_telegram_payload,
    signed_dingtalk_webhook,
    telegram_payload,
)


class SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


def test_adapter_registry_covers_implemented_channels_and_reserves_feishu() -> None:
    assert set(NOTIFICATION_DELIVERY_ADAPTERS) == set(IMPLEMENTED_NOTIFICATION_CHANNELS)
    assert NOTIFICATION_CHANNELS["feishu"].implemented is False
    assert "feishu" not in NOTIFICATION_DELIVERY_ADAPTERS


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


def test_dingtalk_payload_labels_agent_disconnect_as_vps_event() -> None:
    current = event()
    current.source = "agent"
    current.service_kind = None
    current.service_key = None
    current.title = "test-vps: Agent 失联"

    firing = dingtalk_payload(current, "firing", "https://ops.example.com")
    resolved = dingtalk_payload(current, "resolved", "https://ops.example.com")

    assert firing["markdown"]["title"] == "🔴 VPS 失联"  # type: ignore[index]
    assert "**机器**：agent-01" in firing["markdown"]["text"]  # type: ignore[index]
    assert resolved["markdown"]["title"] == "✅ VPS 已恢复连接"  # type: ignore[index]


def test_dingtalk_payload_rejects_unknown_notification_type() -> None:
    with pytest.raises(ValueError, match="unsupported notification type"):
        dingtalk_payload(event(), "custom", "https://ops.example.com")


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
                    json={"errcode": 310000, "errmsg": "access_token=must-not-leak"},
                )
            )
        )
        try:
            with pytest.raises(RuntimeError) as captured:
                await send_dingtalk_notification(settings, event(), "firing", error_client)
            assert str(captured.value) == "DingTalk rejected notification"
            assert "must-not-leak" not in str(captured.value)
        finally:
            await error_client.aclose()

    asyncio.run(rejected())


def test_delivery_failure_persists_only_stable_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    delivery = NotificationDelivery(
        id="delivery-secret-error",
        event_id="event-01",
        notification_type="firing",
        sequence=1,
        channel="dingtalk",
        status="pending",
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    session = AsyncMock()
    session.scalar.return_value = delivery
    session.get.return_value = event()
    signed_request = httpx.Request(
        "POST",
        "https://oapi.dingtalk.com/robot/send"
        "?access_token=must-not-leak&timestamp=123&sign=must-not-leak",
    )
    signed_response = httpx.Response(500, request=signed_request)
    with pytest.raises(httpx.HTTPStatusError) as captured:
        signed_response.raise_for_status()
    remote_error = captured.value
    sender = AsyncMock(side_effect=remote_error)
    monkeypatch.setattr(notifications, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(notifications, "send_notification_delivery", sender)

    asyncio.run(
        deliver_notification(
            delivery.id,
            Settings(
                dingtalk_webhook_url="https://example.test/robot",
                skip_database_init=True,
            ),
        )
    )

    assert "must-not-leak" in str(remote_error)
    assert notification_delivery_error_code(remote_error) == "notification_http_error"
    assert delivery.status == "failed"
    assert delivery.last_error == "notification_http_error"
    assert "must-not-leak" not in delivery.last_error
    assert session.commit.await_count == 2


def test_telegram_payload_uses_frozen_context_and_escapes_html() -> None:
    current_event = event()
    delivery = NotificationDelivery(
        id="delivery-telegram",
        event_id=current_event.id,
        notification_type="firing",
        sequence=1,
        channel="telegram",
        template_key="service_firing",
        template_version="v1",
        render_context={
            "title": "Frozen <title>",
            "detail": "Frozen & detail",
            "source": "service",
            "agent_id": "agent-01",
            "service_kind": "systemd",
            "service_key": "api.service",
        },
    )
    current_event.title = "mutated title"
    current_event.detail = "mutated detail"

    payload = telegram_payload(
        delivery,
        current_event,
        Settings(
            telegram_chat_id="-100123",
            console_public_url="https://ops.example.com",
            skip_database_init=True,
        ),
    )
    serialized = str(payload)

    assert payload["chat_id"] == "-100123"
    assert "Frozen &lt;title&gt;" in serialized
    assert "Frozen &amp; detail" in serialized
    assert "mutated" not in serialized
    assert "https://ops.example.com/events/event-01" in serialized


def test_telegram_sender_uses_fixed_official_origin_and_hides_remote_error() -> None:
    requests: list[httpx.Request] = []

    def success(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        telegram_bot_token="123456:must-not-leak",
        telegram_chat_id="-100123",
        skip_database_init=True,
    )
    payload = {"chat_id": "-100123", "text": "fixed"}
    client = httpx.AsyncClient(transport=httpx.MockTransport(success))
    asyncio.run(send_telegram_payload(settings, payload, client))
    asyncio.run(client.aclose())

    assert len(requests) == 1
    assert requests[0].url.host == "api.telegram.org"
    assert requests[0].url.path == "/bot123456:must-not-leak/sendMessage"

    async def rejected() -> None:
        error_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": False, "description": "token=must-not-leak"},
                )
            )
        )
        try:
            with pytest.raises(RuntimeError) as captured:
                await send_telegram_payload(settings, payload, error_client)
            assert str(captured.value) == "Telegram rejected notification"
            assert "must-not-leak" not in str(captured.value)
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
    monkeypatch.setattr(notifications, "send_notification_delivery", sender)
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
    monkeypatch.setattr(notifications, "send_notification_delivery", sender)
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
