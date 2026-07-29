import base64
import hashlib
import hmac
import html
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import and_, or_, select

from .config import Settings
from .database import session_factory
from .models import AlertEvent, NotificationDelivery
from .notification_catalog import (
    CURRENT_NOTIFICATION_TEMPLATE_VERSION,
    NOTIFICATION_TEMPLATES,
    template_key,
)

MAX_DELIVERY_ATTEMPTS = 3
TELEGRAM_API_ORIGIN = "https://api.telegram.org"


def delivery_is_claimable(
    delivery: NotificationDelivery, stale_before: datetime
) -> bool:
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        return False
    if delivery.status in {"pending", "failed"}:
        return True
    return (
        delivery.status == "sending"
        and delivery.updated_at is not None
        and delivery.updated_at <= stale_before
    )


def notification_delivery_error_code(error: Exception) -> str:
    """Return a stable code without persisting remote text or signed request URLs."""

    if isinstance(error, httpx.TimeoutException):
        return "notification_timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "notification_http_error"
    if isinstance(error, httpx.RequestError):
        return "notification_network_error"
    if isinstance(error, RuntimeError):
        if str(error) in {
            "DingTalk webhook is not configured",
            "Telegram is not configured",
        }:
            return "notification_channel_not_configured"
        if str(error) in {
            "DingTalk rejected notification",
            "Telegram rejected notification",
        }:
            return "notification_rejected"
    if isinstance(error, ValueError | TypeError | AttributeError):
        return "notification_invalid_response"
    return "notification_delivery_error"


def signed_dingtalk_webhook(webhook_url: str, secret: str | None, timestamp_ms: int) -> str:
    if not secret:
        return webhook_url
    string_to_sign = f"{timestamp_ms}\n{secret}"
    signature = base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    parts = urlsplit(webhook_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend([("timestamp", str(timestamp_ms)), ("sign", signature)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def escape_markdown(value: str) -> str:
    escaped = value
    for character in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def event_render_context(event: AlertEvent) -> dict[str, str | None]:
    return {
        "title": event.title,
        "detail": event.detail or "无额外详情",
        "source": event.source,
        "agent_id": event.agent_id,
        "service_kind": event.service_kind,
        "service_key": event.service_key,
    }


def delivery_render_context(
    delivery: NotificationDelivery, event: AlertEvent
) -> dict[str, str | None]:
    raw = delivery.render_context or event_render_context(event)
    if not isinstance(raw, dict):
        raise ValueError("invalid notification render context")
    allowed = {
        "title",
        "detail",
        "source",
        "agent_id",
        "service_kind",
        "service_key",
    }
    if set(raw) - allowed:
        raise ValueError("invalid notification render context")
    context: dict[str, str | None] = {}
    for key in allowed:
        value = raw.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("invalid notification render context")
        context[key] = value
    if not context["title"] or not context["source"] or not context["agent_id"]:
        raise ValueError("invalid notification render context")
    if context["source"] not in {"agent", "service"}:
        raise ValueError("invalid notification render context")
    return context


def notification_template(
    selected_key: str, selected_version: str, notification_type: str
) -> tuple[str, str]:
    definition = NOTIFICATION_TEMPLATES.get((selected_key, selected_version))
    if definition is None:
        raise ValueError("unsupported notification template version")
    if definition.notification_type != notification_type:
        raise ValueError("notification template type mismatch")
    return definition.title, definition.target


def dingtalk_payload_from_context(
    context: dict[str, str | None],
    selected_key: str,
    selected_version: str,
    notification_type: str,
    console_public_url: str,
    event_id: str,
) -> dict[str, object]:
    if notification_type not in {"firing", "resolved"}:
        raise ValueError("unsupported notification type")
    heading, target_kind = notification_template(
        selected_key, selected_version, notification_type
    )
    context_target = "agent" if context["source"] == "agent" else "service"
    if context_target != target_kind:
        raise ValueError("notification template target mismatch")
    resolved = notification_type == "resolved"
    detail = escape_markdown((context["detail"] or "无额外详情")[:300])
    title = escape_markdown(context["title"] or "")
    target_label = "机器" if target_kind == "agent" else "服务"
    target = (
        escape_markdown(context["agent_id"] or "-")
        if target_kind == "agent"
        else escape_markdown(
            f"{context['service_kind'] or 'service'} / {context['service_key'] or '-'}"
        )
    )
    event_url = f"{console_public_url.rstrip('/')}/events/{event_id}"
    text = "\n\n".join(
        [
            f"### {heading}",
            f"- **事件**：{title}",
            f"- **状态**：{'Resolved' if resolved else 'Firing'}",
            f"- **{target_label}**：{target}",
            f"- **详情**：{detail}",
            f"- [查看事件与诊断]({event_url})",
        ]
    )
    return {
        "msgtype": "markdown",
        "markdown": {"title": heading, "text": text},
        "at": {"isAtAll": False},
    }


def dingtalk_payload(
    event: AlertEvent, notification_type: str, console_public_url: str
) -> dict[str, object]:
    if notification_type not in {"firing", "resolved"}:
        raise ValueError("unsupported notification type")
    return dingtalk_payload_from_context(
        event_render_context(event),
        template_key(event.source, notification_type),
        CURRENT_NOTIFICATION_TEMPLATE_VERSION,
        notification_type,
        console_public_url,
        event.id,
    )


def telegram_payload(
    delivery: NotificationDelivery,
    event: AlertEvent,
    settings: Settings,
) -> dict[str, object]:
    context = delivery_render_context(delivery, event)
    heading, target_kind = notification_template(
        delivery.template_key,
        delivery.template_version,
        delivery.notification_type,
    )
    context_target = "agent" if context["source"] == "agent" else "service"
    if context_target != target_kind:
        raise ValueError("notification template target mismatch")
    target_label = "机器" if target_kind == "agent" else "服务"
    target = (
        context["agent_id"] or "-"
        if target_kind == "agent"
        else f"{context['service_kind'] or 'service'} / {context['service_key'] or '-'}"
    )
    event_url = f"{settings.console_public_url.rstrip('/')}/events/{event.id}"
    lines = [
        f"<b>{html.escape(heading)}</b>",
        f"事件：{html.escape(context['title'] or '')}",
        f"状态：{'Resolved' if delivery.notification_type == 'resolved' else 'Firing'}",
        f"{target_label}：{html.escape(target)}",
        f"详情：{html.escape((context['detail'] or '无额外详情')[:300])}",
        f'<a href="{html.escape(event_url, quote=True)}">查看事件与诊断</a>',
    ]
    return {
        "chat_id": settings.telegram_chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


async def send_dingtalk_notification(
    settings: Settings,
    event: AlertEvent,
    notification_type: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    await send_dingtalk_payload(
        settings,
        dingtalk_payload(event, notification_type, settings.console_public_url),
        client,
    )


async def send_dingtalk_payload(
    settings: Settings,
    payload: dict[str, object],
    client: httpx.AsyncClient | None = None,
) -> None:
    if not settings.dingtalk_webhook_url:
        raise RuntimeError("DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = signed_dingtalk_webhook(
        settings.dingtalk_webhook_url, settings.dingtalk_secret, timestamp_ms
    )
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=settings.notification_timeout_seconds)
    try:
        response = await client.post(
            url,
            json=payload,
        )
        response.raise_for_status()
        response_payload = response.json()
        if not isinstance(response_payload, dict):
            raise ValueError("invalid DingTalk response")
        if response_payload.get("errcode") != 0:
            raise RuntimeError("DingTalk rejected notification")
    finally:
        if owns_client:
            await client.aclose()


async def send_telegram_payload(
    settings: Settings,
    payload: dict[str, object],
    client: httpx.AsyncClient | None = None,
) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("Telegram is not configured")
    url = f"{TELEGRAM_API_ORIGIN}/bot{settings.telegram_bot_token}/sendMessage"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=settings.notification_timeout_seconds)
    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        response_payload = response.json()
        if not isinstance(response_payload, dict):
            raise ValueError("invalid Telegram response")
        if response_payload.get("ok") is not True:
            raise RuntimeError("Telegram rejected notification")
    finally:
        if owns_client:
            await client.aclose()


async def deliver_dingtalk_adapter(
    settings: Settings,
    delivery: NotificationDelivery,
    event: AlertEvent,
) -> None:
    context = delivery_render_context(delivery, event)
    await send_dingtalk_payload(
        settings,
        dingtalk_payload_from_context(
            context,
            delivery.template_key,
            delivery.template_version,
            delivery.notification_type,
            settings.console_public_url,
            event.id,
        ),
    )


async def deliver_telegram_adapter(
    settings: Settings,
    delivery: NotificationDelivery,
    event: AlertEvent,
) -> None:
    await send_telegram_payload(settings, telegram_payload(delivery, event, settings))


NOTIFICATION_DELIVERY_ADAPTERS = {
    "dingtalk": deliver_dingtalk_adapter,
    "telegram": deliver_telegram_adapter,
}


async def send_notification_delivery(
    settings: Settings,
    delivery: NotificationDelivery,
    event: AlertEvent,
) -> None:
    adapter = NOTIFICATION_DELIVERY_ADAPTERS.get(delivery.channel)
    if adapter is None:
        raise ValueError("unsupported notification channel")
    await adapter(settings, delivery, event)


def configured_notification_channels(settings: Settings) -> tuple[str, ...]:
    channels: list[str] = []
    if settings.dingtalk_webhook_url:
        channels.append("dingtalk")
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append("telegram")
    return tuple(channels)


async def deliver_notification(delivery_id: str, settings: Settings) -> None:
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=settings.notification_sending_stale_seconds
    )
    async with session_factory() as session:
        delivery = await session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == delivery_id)
            .with_for_update()
        )
        if delivery is None or not delivery_is_claimable(delivery, stale_before):
            return
        delivery.status = "sending"
        delivery.attempt_count += 1
        delivery.last_error = None
        event = await session.get(AlertEvent, delivery.event_id)
        await session.commit()

        if event is None:
            delivery.status = "failed"
            delivery.last_error = "alert event no longer exists"
            await session.commit()
            return

        try:
            await send_notification_delivery(settings, delivery, event)
        except Exception as error:
            delivery.status = "failed"
            delivery.last_error = notification_delivery_error_code(error)
        else:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
        await session.commit()


async def deliver_pending_notifications(settings: Settings) -> None:
    configured_channels = configured_notification_channels(settings)
    if not configured_channels:
        return
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=settings.notification_sending_stale_seconds
    )
    async with session_factory() as session:
        delivery_ids = (
            await session.scalars(
                select(NotificationDelivery.id)
                .where(
                    or_(
                        NotificationDelivery.status.in_(["pending", "failed"]),
                        and_(
                            NotificationDelivery.status == "sending",
                            NotificationDelivery.updated_at <= stale_before,
                        ),
                    ),
                    NotificationDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
                    NotificationDelivery.channel.in_(configured_channels),
                )
                .order_by(NotificationDelivery.created_at)
                .limit(20)
            )
        ).all()
    for delivery_id in delivery_ids:
        await deliver_notification(delivery_id, settings)
