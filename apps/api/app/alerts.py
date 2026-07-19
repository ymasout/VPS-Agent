import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AlertEvent, NotificationDelivery, ServiceStatus
from .schemas import AgentReport, ServiceReport

ACTIVE_STATUSES = ("pending", "firing", "acknowledged", "silenced")


def service_is_problem(service: ServiceReport) -> bool:
    if service.healthy is False:
        return True
    if service.state in {"failed", "unhealthy"}:
        return True
    return service.kind == "docker" and service.state == "exited"


def service_fingerprint(agent_id: str, service: ServiceReport) -> str:
    value = f"{agent_id}|service|{service.kind}|{service.key}"
    return hashlib.sha256(value.encode()).hexdigest()


def agent_availability_fingerprint(agent_id: str) -> str:
    value = f"{agent_id}|agent|availability"
    return hashlib.sha256(value.encode()).hexdigest()


def notification_delivery(event: AlertEvent, notification_type: str) -> NotificationDelivery:
    event.notification_sequence = (event.notification_sequence or 0) + 1
    return NotificationDelivery(
        event_id=event.id,
        notification_type=notification_type,
        sequence=event.notification_sequence,
        channel="dingtalk",
    )


async def evaluate_service_alerts(
    session: AsyncSession,
    agent: Agent,
    report: AgentReport,
    observed_at: datetime,
    pending_observations: int,
    previous_services: list[ServiceStatus] | None = None,
) -> list[NotificationDelivery]:
    active_events = (
        await session.scalars(
            select(AlertEvent).where(
                AlertEvent.agent_id == agent.id,
                AlertEvent.source == "service",
                AlertEvent.status.in_(ACTIVE_STATUSES),
            )
        )
    ).all()
    by_fingerprint = {event.fingerprint: event for event in active_events}
    previous_by_name = {
        (service.kind, service.name): service for service in (previous_services or [])
    }
    deliveries: list[NotificationDelivery] = []

    for service in report.services:
        fingerprint = service_fingerprint(agent.id, service)
        event = by_fingerprint.get(fingerprint)
        previous = previous_by_name.get((service.kind, service.name))
        if event is None and previous is not None and previous.service_key != service.key:
            legacy = ServiceReport(
                kind=service.kind,
                key=previous.service_key,
                name=service.name,
                state=service.state,
            )
            legacy_fingerprint = service_fingerprint(agent.id, legacy)
            event = by_fingerprint.get(legacy_fingerprint)
            if event is not None:
                # Agent 从容器 ID 切换为稳定键时，原活动事件就地迁移，
                # 避免产生第二个 Firing 或让恢复通知永久丢失。
                event.fingerprint = fingerprint
                event.active_key = fingerprint
                event.service_key = service.key
                by_fingerprint.pop(legacy_fingerprint, None)
                by_fingerprint[fingerprint] = event
        if service_is_problem(service):
            if event is None:
                status = "firing" if pending_observations <= 1 else "pending"
                event = AlertEvent(
                    agent_id=agent.id,
                    fingerprint=fingerprint,
                    active_key=fingerprint,
                    source="service",
                    service_kind=service.kind,
                    service_key=service.key,
                    title=f"{agent.name}: {service.name} 异常",
                    severity="critical",
                    status=status,
                    observation_count=1,
                    detail=service.detail,
                    first_observed_at=observed_at,
                    last_observed_at=observed_at,
                    firing_at=observed_at if status == "firing" else None,
                )
                session.add(event)
                await session.flush()
                by_fingerprint[fingerprint] = event
                if status == "firing":
                    deliveries.append(notification_delivery(event, "firing"))
            else:
                event.observation_count += 1
                event.last_observed_at = observed_at
                event.detail = service.detail
                silence_expired = (
                    event.status == "silenced"
                    and event.silenced_until is not None
                    and event.silenced_until <= observed_at
                )
                if silence_expired:
                    event.status = "firing"
                    event.silenced_until = None
                    deliveries.append(notification_delivery(event, "firing"))
                elif event.status == "pending" and event.observation_count >= pending_observations:
                    event.status = "firing"
                    event.firing_at = observed_at
                    deliveries.append(notification_delivery(event, "firing"))
            continue

        if event is not None:
            previous_status = event.status
            event.status = "resolved"
            event.active_key = None
            event.last_observed_at = observed_at
            event.silenced_until = None
            event.resolved_at = observed_at
            if previous_status in {"firing", "acknowledged", "silenced"}:
                deliveries.append(notification_delivery(event, "resolved"))

    session.add_all(deliveries)
    return deliveries


async def evaluate_agent_availability(
    session: AsyncSession,
    agent: Agent,
    observed_at: datetime,
    *,
    online: bool,
    offline_after_seconds: int,
) -> list[NotificationDelivery]:
    """复用 M2 事件状态机记录 Agent 失联与恢复，不引入第二套通知语义。"""

    fingerprint = agent_availability_fingerprint(agent.id)
    event = await session.scalar(
        select(AlertEvent)
        .where(AlertEvent.active_key == fingerprint)
        .with_for_update()
    )
    deliveries: list[NotificationDelivery] = []

    if online:
        if event is None:
            return deliveries
        previous_status = event.status
        event.status = "resolved"
        event.active_key = None
        event.last_observed_at = observed_at
        event.silenced_until = None
        event.resolved_at = observed_at
        event.detail = f"Agent 已恢复上报；恢复时间：{observed_at.isoformat()}"
        if previous_status in {"firing", "acknowledged", "silenced"}:
            deliveries.append(notification_delivery(event, "resolved"))
        session.add_all(deliveries)
        return deliveries

    last_seen = agent.last_seen_at.isoformat() if agent.last_seen_at else "从未上报"
    detail = (
        f"控制平面超过 {offline_after_seconds} 秒未收到 Agent 上报；"
        f"最后心跳：{last_seen}"
    )
    if event is None:
        event = AlertEvent(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            fingerprint=fingerprint,
            active_key=fingerprint,
            source="agent",
            title=f"{agent.name}: Agent 失联",
            severity="critical",
            status="firing",
            observation_count=1,
            detail=detail,
            first_observed_at=observed_at,
            last_observed_at=observed_at,
            firing_at=observed_at,
        )
        session.add(event)
        await session.flush()
        deliveries.append(notification_delivery(event, "firing"))
    else:
        event.observation_count += 1
        event.last_observed_at = observed_at
        event.detail = detail
        silence_expired = (
            event.status == "silenced"
            and event.silenced_until is not None
            and event.silenced_until <= observed_at
        )
        if silence_expired:
            event.status = "firing"
            event.silenced_until = None
            deliveries.append(notification_delivery(event, "firing"))

    session.add_all(deliveries)
    return deliveries
