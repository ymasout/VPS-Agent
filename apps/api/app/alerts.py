import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AlertEvent, NotificationDelivery
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
    deliveries: list[NotificationDelivery] = []

    for service in report.services:
        fingerprint = service_fingerprint(agent.id, service)
        event = by_fingerprint.get(fingerprint)
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
                elif (
                    event.status == "pending"
                    and event.observation_count >= pending_observations
                ):
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
