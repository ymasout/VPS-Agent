import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from .alerts import evaluate_agent_availability
from .config import Settings
from .database import session_factory
from .models import Agent
from .notifications import deliver_pending_notifications
from .operations import recover_stale_operations

logger = structlog.get_logger()


async def reconcile_offline_agents(
    settings: Settings, *, current_time: datetime | None = None
) -> int:
    """锁定并处理已超过心跳阈值的 Agent，保证多实例巡检不会重复建事件。"""

    observed_at = current_time or datetime.now(timezone.utc)
    stale_before = observed_at - timedelta(seconds=settings.agent_offline_after_seconds)
    async with session_factory() as session:
        agents = list(
            (
                await session.scalars(
                    select(Agent)
                    .where(
                        Agent.last_seen_at.is_not(None),
                        Agent.last_seen_at < stale_before,
                    )
                    .order_by(Agent.id)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for agent in agents:
            await evaluate_agent_availability(
                session,
                agent,
                observed_at,
                online=False,
                offline_after_seconds=settings.agent_offline_after_seconds,
            )
        await session.commit()
    return len(agents)


async def run_maintenance_once(settings: Settings) -> None:
    try:
        await reconcile_offline_agents(settings)
    except Exception:
        await logger.aexception("agent.availability_scan_failed")
    try:
        await deliver_pending_notifications(settings)
    except Exception:
        await logger.aexception("notification.pending_delivery_scan_failed")


async def control_plane_maintenance_loop(settings: Settings) -> None:
    """独立于 Agent 上报持续检测失联并重试待发送通知。"""

    # API 重启期间所有心跳都会自然变旧。先给存活 Agent 一个完整阈值重新上报，
    # 避免把控制平面自身停机误报成整批 VPS 失联；通知重试无需等待这段宽限期。
    try:
        await deliver_pending_notifications(settings)
    except Exception:
        await logger.aexception("notification.pending_delivery_scan_failed")
    await asyncio.sleep(settings.agent_offline_after_seconds)
    while True:
        try:
            await recover_stale_operations(settings)
        except Exception:
            await logger.aexception("operation.recovery_scan_failed")
        await run_maintenance_once(settings)
        await asyncio.sleep(settings.agent_availability_scan_interval_seconds)
