from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .api import agent_is_online
from .config import Settings, get_settings
from .database import get_session
from .models import Agent, AlertEvent, MetricSnapshot, Operation, ServiceStatus
from .operations import ACTIVE_STATUSES
from .principal import (
    OPERATION_APPROVE,
    OPERATION_READ,
    require_event_read,
    require_fleet_read,
    require_system_read,
    resolve_principal,
    valid_admin_token,
)
from .schema import current_revisions, expected_revisions
from .schemas import (
    ConsoleOverview,
    OverviewActivityItem,
    OverviewAttentionItem,
    OverviewEventItem,
    OverviewEventSummary,
    OverviewFleetAgent,
    OverviewFleetSummary,
    OverviewOperationItem,
    OverviewOperationSummary,
    OverviewResourceMetric,
    OverviewTrend,
    OverviewTrendPoint,
    OverviewTrustSummary,
)

router = APIRouter(prefix="/api/v1")

MAX_AGENTS = 50
MAX_EVENTS = 100
MAX_OPERATIONS = 50
MAX_RAW_POINTS_PER_AGENT = 1440
MAX_TREND_POINTS = 48
TREND_WINDOW = timedelta(hours=24)
TREND_COVERAGE_TOLERANCE = timedelta(minutes=30)
TREND_GAP_THRESHOLD = timedelta(minutes=5)

TrendStatus = Literal["available", "gapped", "insufficient", "stale", "unavailable"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def resource_tone(value: float | None) -> Literal["neutral", "success", "warning", "danger"]:
    if value is None:
        return "neutral"
    if value >= 85:
        return "danger"
    if value >= 70:
        return "warning"
    return "success"


def _downsample(
    values: list[tuple[datetime, float]], cutoff: datetime
) -> list[OverviewTrendPoint]:
    if not values:
        return []
    bucket_seconds = TREND_WINDOW.total_seconds() / MAX_TREND_POINTS
    buckets: dict[int, tuple[datetime, float]] = {}
    for observed_at, value in sorted(values, key=lambda item: item[0]):
        bucket = min(
            MAX_TREND_POINTS - 1,
            max(0, int((_as_utc(observed_at) - cutoff).total_seconds() / bucket_seconds)),
        )
        buckets[bucket] = (observed_at, value)
    return [
        OverviewTrendPoint(at=observed_at, value=round(value, 2))
        for observed_at, value in (buckets[key] for key in sorted(buckets))
    ]


def build_trend(
    snapshots: list[MetricSnapshot],
    value_of: Callable[[MetricSnapshot], float | None],
    *,
    current_time: datetime,
    stale_after_seconds: int,
) -> OverviewTrend:
    current_time = _as_utc(current_time)
    cutoff = current_time - TREND_WINDOW
    values = [
        (_as_utc(snapshot.collected_at), float(value))
        for snapshot in snapshots
        if (value := value_of(snapshot)) is not None and _as_utc(snapshot.collected_at) >= cutoff
    ]
    values.sort(key=lambda item: item[0])
    if not values:
        return OverviewTrend(status="unavailable", points=[], observed_span_seconds=0)

    oldest, newest = values[0][0], values[-1][0]
    span = max(0, int((newest - oldest).total_seconds()))
    status: TrendStatus
    if newest < current_time - timedelta(seconds=stale_after_seconds):
        status = "stale"
    elif oldest > cutoff + TREND_COVERAGE_TOLERANCE:
        status = "insufficient"
    elif any(
        right[0] - left[0] > TREND_GAP_THRESHOLD
        for left, right in zip(values, values[1:], strict=False)
    ):
        status = "gapped"
    else:
        status = "available"
    return OverviewTrend(
        status=status,
        points=_downsample(values, cutoff),
        observed_span_seconds=span,
    )


def disk_percent(snapshot: MetricSnapshot) -> float | None:
    values = [
        float(item["used_percent"])
        for item in snapshot.disks or []
        if isinstance(item, dict) and isinstance(item.get("used_percent"), int | float)
    ]
    return max(values) if values else None


def operation_target(operation: Operation) -> str:
    plan = operation.plan_snapshot if isinstance(operation.plan_snapshot, dict) else {}
    machine = plan.get("machine") if isinstance(plan.get("machine"), dict) else {}
    service = plan.get("service") if isinstance(plan.get("service"), dict) else {}
    machine_name = machine.get("name") or machine.get("hostname") or operation.agent_id
    service_name = service.get("name")
    target = f"{service_name} · {machine_name}" if service_name else str(machine_name)
    return target[:160]


def operation_access(
    request: Request, settings: Settings, supplied_admin_token: str | None
) -> tuple[bool, bool]:
    if not settings.principal_write_authorization_enabled:
        return True, True
    try:
        principal = resolve_principal(request, settings)
    except HTTPException:
        principal = None
    if principal is not None:
        return OPERATION_READ in principal.capabilities, OPERATION_APPROVE in principal.capabilities
    if valid_admin_token(supplied_admin_token, settings):
        # M6 named authorization deliberately does not let the legacy admin token read
        # Operation details once enforcement is enabled.
        return False, False
    return False, False


def _event_target(event: AlertEvent, agent_names: dict[str, str]) -> str:
    return event.service_key or agent_names.get(event.agent_id, event.agent_id)


def _event_tone(event: AlertEvent) -> Literal["info", "warning", "danger"]:
    if event.status == "resolved":
        return "info"
    return "danger" if event.severity == "critical" else "warning"


def _activity_tone_for_operation(
    status: str,
) -> Literal["info", "success", "warning", "danger"]:
    if status == "succeeded":
        return "success"
    if status in {"failed", "expired", "canceled", "rejected"}:
        return "danger"
    if status == "awaiting_confirmation":
        return "warning"
    return "info"


def latest_metrics_query(agent_ids: list[str], cutoff: datetime):
    """Fetch one recent snapshot per agent without scanning unbounded history."""
    latest_lateral = (
        select(MetricSnapshot)
        .where(
            MetricSnapshot.agent_id == Agent.id,
            MetricSnapshot.collected_at >= cutoff,
        )
        .order_by(MetricSnapshot.collected_at.desc(), MetricSnapshot.id.desc())
        .limit(1)
        .lateral("latest_metric")
    )
    latest_metric = aliased(MetricSnapshot, latest_lateral)
    return (
        select(latest_metric)
        .select_from(Agent)
        .join(latest_lateral, true())
        .where(Agent.organization_id == "local", Agent.id.in_(agent_ids))
    )


@router.get(
    "/console-overview",
    response_model=ConsoleOverview,
    dependencies=[
        Depends(require_system_read),
        Depends(require_fleet_read),
        Depends(require_event_read),
    ],
)
async def console_overview(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConsoleOverview:
    current_time = now_utc()
    cutoff = current_time - TREND_WINDOW
    agents = list(
        (
            await session.scalars(
                select(Agent)
                .where(Agent.organization_id == "local")
                .order_by(Agent.name, Agent.id)
                .limit(MAX_AGENTS)
            )
        ).all()
    )
    agent_ids = [agent.id for agent in agents]
    agent_names = {agent.id: agent.name for agent in agents}
    fleet_total = int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(Agent.organization_id == "local")
        )
        or 0
    )
    online_total = int(
        await session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.organization_id == "local",
                Agent.last_seen_at >= current_time - timedelta(
                    seconds=settings.agent_offline_after_seconds
                ),
            )
        )
        or 0
    )
    unhealthy_total = int(
        await session.scalar(
            select(func.count())
            .select_from(ServiceStatus)
            .join(Agent, Agent.id == ServiceStatus.agent_id)
            .where(
                Agent.organization_id == "local",
                ServiceStatus.healthy.is_(False)
                | ServiceStatus.state.in_(["failed", "unhealthy"]),
            )
        )
        or 0
    )

    problem_counts: dict[str, int] = {}
    latest_by_agent: dict[str, MetricSnapshot] = {}
    history_by_agent: dict[str, list[MetricSnapshot]] = {}
    if agent_ids:
        problem_counts = {
            agent_id: int(count)
            for agent_id, count in (
                await session.execute(
                    select(ServiceStatus.agent_id, func.count())
                    .where(
                        ServiceStatus.agent_id.in_(agent_ids),
                        ServiceStatus.healthy.is_(False)
                        | ServiceStatus.state.in_(["failed", "unhealthy"]),
                    )
                    .group_by(ServiceStatus.agent_id)
                )
            ).all()
        }

        latest_rows = list(
            (await session.scalars(latest_metrics_query(agent_ids, cutoff))).all()
        )
        latest_by_agent = {item.agent_id: item for item in latest_rows}

        history_ranked = (
            select(
                MetricSnapshot.id.label("metric_id"),
                func.row_number()
                .over(
                    partition_by=MetricSnapshot.agent_id,
                    order_by=(MetricSnapshot.collected_at.desc(), MetricSnapshot.id.desc()),
                )
                .label("snapshot_rank"),
            )
            .where(
                MetricSnapshot.agent_id.in_(agent_ids),
                MetricSnapshot.collected_at >= cutoff,
            )
            .subquery()
        )
        history_rows = list(
            (
                await session.scalars(
                    select(MetricSnapshot)
                    .join(history_ranked, history_ranked.c.metric_id == MetricSnapshot.id)
                    .where(history_ranked.c.snapshot_rank <= MAX_RAW_POINTS_PER_AGENT)
                    .order_by(MetricSnapshot.agent_id, MetricSnapshot.collected_at.desc())
                )
            ).all()
        )
        for item in history_rows:
            history_by_agent.setdefault(item.agent_id, []).append(item)

    fleet_agents: list[OverviewFleetAgent] = []
    for agent in agents:
        latest = latest_by_agent.get(agent.id)
        history = history_by_agent.get(agent.id, [])
        current_disk = disk_percent(latest) if latest else None
        fleet_agents.append(
            OverviewFleetAgent(
                id=agent.id,
                name=agent.name,
                hostname=agent.hostname,
                online=agent_is_online(
                    agent.last_seen_at, current_time, settings.agent_offline_after_seconds
                ),
                version=agent.version,
                last_seen_at=agent.last_seen_at,
                service_problem_count=problem_counts.get(agent.id, 0),
                cpu=OverviewResourceMetric(
                    current_percent=latest.cpu_percent if latest else None,
                    tone=resource_tone(latest.cpu_percent if latest else None),
                    trend=build_trend(
                        history,
                        lambda item: item.cpu_percent,
                        current_time=current_time,
                        stale_after_seconds=settings.agent_offline_after_seconds,
                    ),
                ),
                memory=OverviewResourceMetric(
                    current_percent=latest.memory_percent if latest else None,
                    tone=resource_tone(latest.memory_percent if latest else None),
                    trend=build_trend(
                        history,
                        lambda item: item.memory_percent,
                        current_time=current_time,
                        stale_after_seconds=settings.agent_offline_after_seconds,
                    ),
                ),
                disk=OverviewResourceMetric(
                    current_percent=current_disk,
                    tone=resource_tone(current_disk),
                    trend=build_trend(
                        history,
                        disk_percent,
                        current_time=current_time,
                        stale_after_seconds=settings.agent_offline_after_seconds,
                    ),
                ),
            )
        )

    events = list(
        (
            await session.scalars(
                select(AlertEvent)
                .where(AlertEvent.organization_id == "local")
                .order_by(AlertEvent.last_observed_at.desc(), AlertEvent.id)
                .limit(MAX_EVENTS)
            )
        ).all()
    )
    attention_events = list(
        (
            await session.scalars(
                select(AlertEvent)
                .where(
                    AlertEvent.organization_id == "local",
                    AlertEvent.status != "resolved",
                )
                .order_by(
                    AlertEvent.severity,
                    AlertEvent.last_observed_at.desc(),
                    AlertEvent.id,
                )
                .limit(4)
            )
        ).all()
    )
    event_counts = {
        (severity, event_status): int(count)
        for severity, event_status, count in (
            await session.execute(
                select(AlertEvent.severity, AlertEvent.status, func.count())
                .where(AlertEvent.organization_id == "local")
                .group_by(AlertEvent.severity, AlertEvent.status)
            )
        ).all()
    }
    active_event_count = sum(
        count for (_, event_status), count in event_counts.items() if event_status != "resolved"
    )
    critical_event_count = sum(
        count
        for (severity, event_status), count in event_counts.items()
        if severity == "critical" and event_status != "resolved"
    )
    warning_event_count = sum(
        count
        for (severity, event_status), count in event_counts.items()
        if severity == "warning" and event_status != "resolved"
    )

    operations_available, can_approve = operation_access(request, settings, x_admin_token)
    operations: list[Operation] = []
    if operations_available:
        operations = list(
            (
                await session.scalars(
                    select(Operation)
                    .where(Operation.organization_id == "local")
                    .order_by(Operation.updated_at.desc(), Operation.id)
                    .limit(MAX_OPERATIONS)
                )
            ).all()
        )
    active_operations = [item for item in operations if item.status in ACTIVE_STATUSES]
    operation_counts: dict[str, int] = {}
    if operations_available:
        operation_counts = {
            operation_status: int(count)
            for operation_status, count in (
                await session.execute(
                    select(Operation.status, func.count())
                    .where(Operation.organization_id == "local")
                    .group_by(Operation.status)
                )
            ).all()
        }

    offline_agents = list(
        (
            await session.scalars(
                select(Agent)
                .where(
                    Agent.organization_id == "local",
                    (Agent.last_seen_at.is_(None))
                    | (
                        Agent.last_seen_at
                        < current_time
                        - timedelta(seconds=settings.agent_offline_after_seconds)
                    ),
                )
                .order_by(Agent.last_seen_at.asc().nullsfirst(), Agent.name, Agent.id)
                .limit(6)
            )
        ).all()
    )

    attention: list[OverviewAttentionItem] = [
        OverviewAttentionItem(
            kind="event",
            title=event.title,
            target=_event_target(event, agent_names),
            tone=_event_tone(event),
            occurred_at=event.last_observed_at,
            href=f"/events/{event.id}",
        )
        for event in attention_events
    ]
    if operations_available:
        attention.extend(
            OverviewAttentionItem(
                kind="operation",
                title=(
                    "Operation 等待独立审批"
                    if operation.status == "awaiting_confirmation"
                    else "Operation 需要复核"
                ),
                target=operation_target(operation),
                tone="warning" if operation.status == "awaiting_confirmation" else "danger",
                occurred_at=operation.updated_at,
                href=f"/operations/{operation.id}",
            )
            for operation in operations
            if operation.status == "awaiting_confirmation"
            or (
                operation.status in {"failed", "expired"}
                and _as_utc(operation.updated_at) >= cutoff
            )
        )
    attention.extend(
        OverviewAttentionItem(
            kind="agent",
            title="机器离线",
            target=agent.name,
            tone="danger",
            occurred_at=agent.last_seen_at or agent.created_at,
            href=f"/servers/{agent.id}",
        )
        for agent in offline_agents
    )
    attention.sort(key=lambda item: _as_utc(item.occurred_at), reverse=True)

    activity: list[OverviewActivityItem] = [
        OverviewActivityItem(
            kind="event",
            label=("事件已恢复" if event.status == "resolved" else event.title),
            target=_event_target(event, agent_names),
            tone=("success" if event.status == "resolved" else _event_tone(event)),
            occurred_at=event.last_observed_at,
            href=f"/events/{event.id}",
        )
        for event in events[:8]
    ]
    activity.extend(
        OverviewActivityItem(
            kind="operation",
            label=f"Operation · {operation.status}",
            target=operation_target(operation),
            tone=_activity_tone_for_operation(operation.status),
            occurred_at=operation.updated_at,
            href=f"/operations/{operation.id}",
        )
        for operation in operations[:8]
    )
    activity.sort(key=lambda item: _as_utc(item.occurred_at), reverse=True)

    expected = sorted(expected_revisions())
    current = (
        []
        if settings.skip_database_init
        else sorted(await current_revisions(await session.connection()))
    )
    return ConsoleOverview(
        generated_at=current_time,
        fleet=OverviewFleetSummary(
            total=fleet_total,
            online=online_total,
            unhealthy_services=unhealthy_total,
        ),
        events=OverviewEventSummary(
            active=active_event_count,
            critical=critical_event_count,
            warning=warning_event_count,
        ),
        attention=attention[:6],
        agents=fleet_agents,
        event_items=[
            OverviewEventItem(
                id=event.id,
                title=event.title,
                target=_event_target(event, agent_names),
                severity=event.severity,
                status=event.status,
                occurred_at=event.last_observed_at,
            )
            for event in events[:5]
        ],
        operations=OverviewOperationSummary(
            available=operations_available,
            can_approve=can_approve,
            pending_approval=operation_counts.get("awaiting_confirmation", 0),
            active=sum(operation_counts.get(item, 0) for item in ACTIVE_STATUSES),
            items=[
                OverviewOperationItem(
                    id=operation.id,
                    action_type=operation.action_type,
                    status=operation.status,
                    target=operation_target(operation),
                    impact_summary=operation.impact_summary,
                    requested_at=operation.requested_at,
                    expires_at=operation.expires_at,
                )
                for operation in active_operations[:4]
            ],
        ),
        recent_activity=activity[:8],
        trust=OverviewTrustSummary(
            analysis_mode=(
                "rules"
                if settings.diagnostic_provider == "deterministic"
                and settings.conversation_provider == "deterministic"
                else "model"
            ),
            version=settings.control_plane_version,
            commit_sha=settings.control_plane_commit_sha,
            schema_current=current == expected,
            schema_revision=current,
        ),
    )
