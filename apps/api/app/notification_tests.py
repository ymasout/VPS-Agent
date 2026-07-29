from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import require_admin
from .config import Settings, get_settings
from .database import get_session, session_factory
from .models import NotificationTestRequest
from .notifications import send_dingtalk_payload, send_telegram_payload
from .schemas import NotificationTestView

router = APIRouter(prefix="/api/v1")
ORGANIZATION_ID = "local"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def rate_limit_window(current_time: datetime, cooldown_seconds: int) -> datetime:
    epoch = int(current_time.timestamp())
    return datetime.fromtimestamp(
        epoch - (epoch % cooldown_seconds), tz=timezone.utc
    )


def rate_limit_error(
    window: datetime, current_time: datetime, cooldown_seconds: int
) -> HTTPException:
    retry_after = max(
        1,
        int(
            (
                window + timedelta(seconds=cooldown_seconds) - current_time
            ).total_seconds()
        ),
    )
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="notification test rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )


def test_payload(request: NotificationTestRequest) -> dict[str, object]:
    heading = "✅ VPS Agent 通知测试"
    text = "\n\n".join(
        [
            f"### {heading}",
            "- **类型**：管理员显式测试消息",
            "- **结果**：如果你看到本消息，钉钉通知链已连通",
            f"- **审计 ID**：`{request.id}`",
            "- 本消息不会创建告警、诊断或运维操作",
        ]
    )
    return {
        "msgtype": "markdown",
        "markdown": {"title": heading, "text": text},
        "at": {"isAtAll": False},
    }


def telegram_test_payload(
    request: NotificationTestRequest, settings: Settings
) -> dict[str, object]:
    return {
        "chat_id": settings.telegram_chat_id,
        "text": "\n".join(
            [
                "✅ VPS Agent 通知测试",
                "类型：管理员显式测试消息",
                "结果：如果你看到本消息，Telegram 通知链已连通",
                f"审计 ID：{request.id}",
                "本消息不会创建告警、诊断或运维操作",
            ]
        ),
        "disable_web_page_preview": True,
    }


def channel_is_configured(channel: str, settings: Settings) -> bool:
    if channel not in settings.enabled_notification_channels:
        return False
    if channel == "dingtalk":
        return bool(settings.dingtalk_webhook_url)
    if channel == "telegram":
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)
    return False


def delivery_error_code(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "notification_test_timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "notification_test_http_error"
    if isinstance(error, httpx.RequestError):
        return "notification_test_network_error"
    if isinstance(error, RuntimeError):
        message = str(error)
        if message in {"DingTalk webhook is not configured", "Telegram is not configured"}:
            return "notification_channel_not_configured"
        if message in {
            "DingTalk rejected notification",
            "Telegram rejected notification",
        }:
            return "notification_test_rejected"
    if isinstance(error, ValueError):
        return "notification_test_invalid_response"
    return "notification_test_delivery_unknown"


def delivery_failure_status(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return "failed"
    if isinstance(error, RuntimeError):
        return "failed"
    return "delivery_outcome_unknown"


def to_view(request: NotificationTestRequest) -> NotificationTestView:
    return NotificationTestView(
        id=request.id,
        channel=request.channel,
        status=request.status,
        attempt_count=request.attempt_count,
        error_code=request.error_code,
        requested_by=request.requested_by,
        created_at=request.created_at,
        started_at=request.started_at,
        completed_at=request.completed_at,
    )


async def require_empty_body(request: Request) -> None:
    if await request.body():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="request body is not allowed",
        )


async def deliver_notification_test(request_id: str, settings: Settings) -> None:
    async with session_factory() as session:
        request = await session.scalar(
            select(NotificationTestRequest)
            .where(NotificationTestRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.status != "pending" or request.attempt_count != 0:
            return
        if not settings.notification_tests_enabled:
            request.status = "failed"
            request.error_code = "notification_tests_disabled"
            request.completed_at = now_utc()
            await session.commit()
            return
        request.status = "sending"
        request.attempt_count = 1
        request.started_at = now_utc()
        request.error_code = None
        await session.commit()
        channel = request.channel
        payload = (
            test_payload(request)
            if channel == "dingtalk"
            else telegram_test_payload(request, settings)
        )

    error_code: str | None = None
    failure_status: str | None = None
    try:
        if channel == "dingtalk":
            await send_dingtalk_payload(settings, payload)
        elif channel == "telegram":
            await send_telegram_payload(settings, payload)
        else:
            raise ValueError("unsupported notification test channel")
    except Exception as error:
        error_code = delivery_error_code(error)
        failure_status = delivery_failure_status(error)

    async with session_factory() as session:
        request = await session.scalar(
            select(NotificationTestRequest)
            .where(NotificationTestRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.status != "sending":
            return
        request.status = failure_status or "succeeded"
        request.error_code = error_code
        request.completed_at = now_utc()
        await session.commit()


async def maintain_notification_tests(settings: Settings) -> None:
    stale_before = now_utc() - timedelta(
        seconds=settings.notification_sending_stale_seconds
    )
    async with session_factory() as session:
        stale = list(
            (
                await session.scalars(
                    select(NotificationTestRequest)
                    .where(
                        NotificationTestRequest.status == "sending",
                        NotificationTestRequest.updated_at <= stale_before,
                    )
                    .order_by(NotificationTestRequest.created_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for request in stale:
            request.status = "delivery_outcome_unknown"
            request.error_code = "notification_test_delivery_outcome_unknown"
            request.completed_at = now_utc()
        await session.commit()

    if not settings.notification_tests_enabled:
        async with session_factory() as session:
            pending = list(
                (
                    await session.scalars(
                        select(NotificationTestRequest)
                        .where(
                            NotificationTestRequest.status == "pending",
                            NotificationTestRequest.attempt_count == 0,
                        )
                        .order_by(NotificationTestRequest.created_at)
                        .limit(20)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for request in pending:
                request.status = "failed"
                request.error_code = "notification_tests_disabled"
                request.completed_at = now_utc()
            await session.commit()
        return

    async with session_factory() as session:
        pending_ids = list(
            (
                await session.scalars(
                    select(NotificationTestRequest.id)
                    .where(
                        NotificationTestRequest.status == "pending",
                        NotificationTestRequest.attempt_count == 0,
                    )
                    .order_by(NotificationTestRequest.created_at)
                    .limit(20)
                )
            ).all()
        )
    for request_id in pending_ids:
        await deliver_notification_test(request_id, settings)


@router.post(
    "/notification-tests/dingtalk",
    response_model=NotificationTestView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin), Depends(require_empty_body)],
)
async def create_notification_test(
    background_tasks: BackgroundTasks,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NotificationTestView:
    return await create_notification_test_for_channel(
        "dingtalk",
        background_tasks,
        response,
        idempotency_key,
        session,
        settings,
    )


@router.post(
    "/notification-tests/telegram",
    response_model=NotificationTestView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin), Depends(require_empty_body)],
)
async def create_telegram_notification_test(
    background_tasks: BackgroundTasks,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NotificationTestView:
    return await create_notification_test_for_channel(
        "telegram",
        background_tasks,
        response,
        idempotency_key,
        session,
        settings,
    )


async def create_notification_test_for_channel(
    channel: str,
    background_tasks: BackgroundTasks,
    response: Response,
    idempotency_key: UUID,
    session: AsyncSession,
    settings: Settings,
) -> NotificationTestView:
    client_request_id = str(idempotency_key)
    existing = await session.scalar(
        select(NotificationTestRequest).where(
            NotificationTestRequest.organization_id == ORGANIZATION_ID,
            NotificationTestRequest.channel == channel,
            NotificationTestRequest.client_request_id == client_request_id,
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return to_view(existing)
    if not settings.notification_tests_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="notification tests are disabled",
        )
    if not channel_is_configured(channel, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notification channel is not configured",
        )

    current_time = now_utc()
    window = rate_limit_window(
        current_time, settings.notification_test_cooldown_seconds
    )
    window_request = await session.scalar(
        select(NotificationTestRequest).where(
            NotificationTestRequest.organization_id == ORGANIZATION_ID,
            NotificationTestRequest.channel == channel,
            NotificationTestRequest.rate_limit_window == window,
        )
    )
    if window_request is not None:
        raise rate_limit_error(
            window, current_time, settings.notification_test_cooldown_seconds
        )
    request = NotificationTestRequest(
        organization_id=ORGANIZATION_ID,
        channel=channel,
        client_request_id=client_request_id,
        rate_limit_window=window,
        status="pending",
        attempt_count=0,
        requested_by="local-admin",
        created_at=current_time,
        updated_at=current_time,
    )
    session.add(request)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(NotificationTestRequest).where(
                NotificationTestRequest.organization_id == ORGANIZATION_ID,
                NotificationTestRequest.channel == channel,
                NotificationTestRequest.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return to_view(existing)
        window_request = await session.scalar(
            select(NotificationTestRequest).where(
                NotificationTestRequest.organization_id == ORGANIZATION_ID,
                NotificationTestRequest.channel == channel,
                NotificationTestRequest.rate_limit_window == window,
            )
        )
        if window_request is not None:
            raise rate_limit_error(
                window, current_time, settings.notification_test_cooldown_seconds
            ) from None
        raise error

    await session.refresh(request)
    background_tasks.add_task(deliver_notification_test, request.id, settings)
    return to_view(request)


@router.get(
    "/notification-tests",
    response_model=list[NotificationTestView],
    dependencies=[Depends(require_admin)],
)
async def list_notification_tests(
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationTestView]:
    requests = list(
        (
            await session.scalars(
                select(NotificationTestRequest)
                .where(NotificationTestRequest.organization_id == ORGANIZATION_ID)
                .order_by(NotificationTestRequest.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [to_view(request) for request in requests]


@router.get(
    "/notification-tests/{request_id}",
    response_model=NotificationTestView,
    dependencies=[Depends(require_admin)],
)
async def get_notification_test(
    request_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> NotificationTestView:
    request = await session.scalar(
        select(NotificationTestRequest).where(
            NotificationTestRequest.id == str(request_id),
            NotificationTestRequest.organization_id == ORGANIZATION_ID,
        )
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification test not found",
        )
    return to_view(request)
