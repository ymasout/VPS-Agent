import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import and_, or_, select

from .config import Settings
from .database import session_factory
from .models import AlertEvent, NotificationDelivery


def delivery_is_claimable(
    delivery: NotificationDelivery, stale_before: datetime
) -> bool:
    if delivery.attempt_count >= 3:
        return False
    if delivery.status in {"pending", "failed"}:
        return True
    return (
        delivery.status == "sending"
        and delivery.updated_at is not None
        and delivery.updated_at <= stale_before
    )


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


def dingtalk_payload(
    event: AlertEvent, notification_type: str, console_public_url: str
) -> dict[str, object]:
    resolved = notification_type == "resolved"
    agent_event = event.source == "agent"
    if agent_event:
        heading = "✅ VPS 已恢复连接" if resolved else "🔴 VPS 失联"
    else:
        heading = "✅ 服务已恢复" if resolved else "🔴 服务异常"
    status = "Resolved" if resolved else "Firing"
    detail = escape_markdown((event.detail or "无额外详情")[:300])
    title = escape_markdown(event.title)
    target_label = "机器" if agent_event else "服务"
    target = (
        escape_markdown(event.agent_id)
        if agent_event
        else escape_markdown(f"{event.service_kind or 'service'} / {event.service_key or '-'}")
    )
    event_url = f"{console_public_url.rstrip('/')}/events/{event.id}"
    text = "\n\n".join(
        [
            f"### {heading}",
            f"- **事件**：{title}",
            f"- **状态**：{status}",
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


async def send_dingtalk_notification(
    settings: Settings,
    event: AlertEvent,
    notification_type: str,
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
            json=dingtalk_payload(event, notification_type, settings.console_public_url),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errcode") != 0:
            message = payload.get("errmsg", "unknown")
            raise RuntimeError(f"DingTalk rejected notification: {message}")
    finally:
        if owns_client:
            await client.aclose()


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
            await send_dingtalk_notification(
                settings, event, delivery.notification_type
            )
        except Exception as error:
            delivery.status = "failed"
            delivery.last_error = str(error)[:512]
        else:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
        await session.commit()


async def deliver_pending_notifications(settings: Settings) -> None:
    if not settings.dingtalk_webhook_url:
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
                    NotificationDelivery.attempt_count < 3,
                )
                .order_by(NotificationDelivery.created_at)
                .limit(20)
            )
        ).all()
    for delivery_id in delivery_ids:
        await deliver_notification(delivery_id, settings)
