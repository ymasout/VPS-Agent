from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .alerts import evaluate_agent_availability, evaluate_service_alerts
from .config import Settings, get_settings
from .database import get_session
from .models import (
    Agent,
    AgentEvidenceSource,
    AgentEvidenceSourceBinding,
    AlertEvent,
    MetricSnapshot,
    RegistrationToken,
    ServiceInstance,
    ServiceStatus,
)
from .notifications import deliver_pending_notifications
from .schemas import (
    AgentDetail,
    AgentRegister,
    AgentRegistered,
    AgentReport,
    AgentSummary,
    AlertEventAction,
    AlertEventView,
    MetricView,
    RegistrationTokenCreate,
    RegistrationTokenCreated,
    ReportReceipt,
    ServiceView,
)
from .security import generate_token, hash_token

router = APIRouter(prefix="/api/v1")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def agent_is_online(
    last_seen_at: datetime | None, current_time: datetime, offline_after: int
) -> bool:
    return bool(last_seen_at and last_seen_at >= current_time - timedelta(seconds=offline_after))


async def require_admin(
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_admin_token or hash_token(x_admin_token) != hash_token(settings.admin_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token")


async def current_agent(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Agent:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing credential")
    credential_hash = hash_token(authorization.removeprefix("Bearer ").strip())
    agent = await session.scalar(select(Agent).where(Agent.credential_hash == credential_hash))
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credential")
    return agent


@router.post(
    "/registration-tokens",
    response_model=RegistrationTokenCreated,
    dependencies=[Depends(require_admin)],
)
async def create_registration_token(
    payload: RegistrationTokenCreate, session: AsyncSession = Depends(get_session)
) -> RegistrationTokenCreated:
    token = generate_token("reg")
    expires_at = now_utc() + timedelta(minutes=payload.expires_in_minutes)
    session.add(
        RegistrationToken(token_hash=hash_token(token), name=payload.name, expires_at=expires_at)
    )
    await session.commit()
    return RegistrationTokenCreated(token=token, expires_at=expires_at)


@router.post(
    "/agents/register", response_model=AgentRegistered, status_code=status.HTTP_201_CREATED
)
async def register_agent(
    payload: AgentRegister,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AgentRegistered:
    token = await session.scalar(
        select(RegistrationToken)
        .where(RegistrationToken.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    current_time = now_utc()
    if token is None or token.used_at is not None or token.expires_at < current_time:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired registration token"
        )
    existing = await session.scalar(select(Agent).where(Agent.machine_id == payload.machine_id))
    credential = generate_token("agt")
    if existing is not None:
        if agent_is_online(
            existing.last_seen_at, current_time, settings.agent_offline_after_seconds
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="machine is already online; check for a duplicated machine-id",
            )
        existing.credential_hash = hash_token(credential)
        existing.name = payload.name
        existing.hostname = payload.hostname
        existing.os = payload.os
        existing.arch = payload.arch
        existing.version = payload.version
        existing.capabilities = payload.capabilities
        existing.last_seen_at = current_time
        agent = existing
    else:
        agent = Agent(
            credential_hash=hash_token(credential),
            name=payload.name,
            hostname=payload.hostname,
            machine_id=payload.machine_id,
            os=payload.os,
            arch=payload.arch,
            version=payload.version,
            capabilities=payload.capabilities,
            last_seen_at=current_time,
        )
        session.add(agent)
    token.used_at = current_time
    await session.commit()
    await session.refresh(agent)
    return AgentRegistered(agent_id=agent.id, credential=credential)


@router.post("/agents/report", response_model=ReportReceipt)
async def report_agent(
    payload: AgentReport,
    background_tasks: BackgroundTasks,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReportReceipt:
    received_at = now_utc()
    locked_agent = await session.scalar(
        select(Agent).where(Agent.id == agent.id).with_for_update()
    )
    if locked_agent is None:
        raise HTTPException(status_code=401, detail="agent not found")
    await evaluate_agent_availability(
        session,
        locked_agent,
        received_at,
        online=True,
        offline_after_seconds=settings.agent_offline_after_seconds,
    )
    locked_agent.hostname = payload.hostname
    locked_agent.version = payload.version
    locked_agent.capabilities = payload.capabilities
    locked_agent.last_seen_at = received_at
    previous_services = list(
        (
            await session.scalars(select(ServiceStatus).where(ServiceStatus.agent_id == agent.id))
        ).all()
    )
    await evaluate_service_alerts(
        session,
        locked_agent,
        payload,
        received_at,
        settings.alert_pending_observations,
        previous_services,
    )
    await reconcile_service_instance_keys(session, agent.id, payload, previous_services)
    session.add(
        MetricSnapshot(
            agent_id=agent.id,
            cpu_percent=payload.metrics.cpu_percent,
            memory_percent=payload.metrics.memory_percent,
            memory_used_bytes=payload.metrics.memory_used_bytes,
            memory_total_bytes=payload.metrics.memory_total_bytes,
            disks=[disk.model_dump() for disk in payload.metrics.disks],
            collected_at=payload.collected_at,
        )
    )
    await session.execute(delete(ServiceStatus).where(ServiceStatus.agent_id == agent.id))
    await session.execute(
        delete(AgentEvidenceSource).where(AgentEvidenceSource.agent_id == agent.id)
    )
    session.add_all(
        [
            ServiceStatus(
                agent_id=agent.id,
                kind=item.kind,
                service_key=item.key,
                name=item.name,
                state=item.state,
                detail=item.detail,
                healthy=item.healthy,
                observed_at=payload.collected_at,
            )
            for item in payload.services
        ]
    )
    evidence_sources = [
        AgentEvidenceSource(
            agent_id=agent.id,
            source_key=item.key,
            kind=item.kind,
            display_name=item.display_name,
            observed_at=payload.collected_at,
        )
        for item in payload.evidence_sources
    ]
    session.add_all(evidence_sources)
    await session.flush()
    session.add_all(
        [
            AgentEvidenceSourceBinding(
                evidence_source_id=source.id,
                service_kind=item.service_kind,
                service_key=item.service_key,
                observed_at=payload.collected_at,
            )
            for source, item in zip(evidence_sources, payload.evidence_sources, strict=True)
            if item.service_kind is not None and item.service_key is not None
        ]
    )
    await session.commit()
    if settings.dingtalk_webhook_url:
        background_tasks.add_task(deliver_pending_notifications, settings)
    return ReportReceipt(received_at=received_at)


async def reconcile_service_instance_keys(
    session: AsyncSession,
    agent_id: str,
    report: AgentReport,
    previous_services: list[ServiceStatus],
) -> None:
    """将既有 M3 映射从 Docker 容器 ID 平滑迁移到稳定服务键。"""

    previous_by_key = {
        (service.kind, service.service_key): service for service in previous_services
    }
    current_by_name = {(service.kind, service.name): service for service in report.services}
    instances = list(
        (
            await session.scalars(
                select(ServiceInstance).where(ServiceInstance.agent_id == agent_id)
            )
        ).all()
    )
    for instance in instances:
        previous = previous_by_key.get((instance.service_kind, instance.service_key))
        if previous is None:
            continue
        current = current_by_name.get((previous.kind, previous.name))
        if current is not None and current.key != instance.service_key:
            instance.service_key = current.key


async def build_summary(agent: Agent, session: AsyncSession, offline_after: int) -> AgentSummary:
    metric = await session.scalar(
        select(MetricSnapshot)
        .where(MetricSnapshot.agent_id == agent.id)
        .order_by(MetricSnapshot.collected_at.desc())
        .limit(1)
    )
    counts = dict(
        (
            await session.execute(
                select(ServiceStatus.state, func.count())
                .where(ServiceStatus.agent_id == agent.id)
                .group_by(ServiceStatus.state)
            )
        ).all()
    )
    kind_counts = dict(
        (
            await session.execute(
                select(ServiceStatus.kind, func.count())
                .where(ServiceStatus.agent_id == agent.id)
                .group_by(ServiceStatus.kind)
            )
        ).all()
    )
    problem_count = await session.scalar(
        select(func.count())
        .select_from(ServiceStatus)
        .where(
            ServiceStatus.agent_id == agent.id,
            ServiceStatus.healthy.is_(False) | ServiceStatus.state.in_(["failed", "unhealthy"]),
        )
    )
    online = agent_is_online(agent.last_seen_at, now_utc(), offline_after)
    metric_view = None
    if metric:
        metric_view = MetricView(
            cpu_percent=metric.cpu_percent,
            memory_percent=metric.memory_percent,
            memory_used_bytes=metric.memory_used_bytes,
            memory_total_bytes=metric.memory_total_bytes,
            disks=metric.disks,
            collected_at=metric.collected_at,
        )
    return AgentSummary(
        id=agent.id,
        name=agent.name,
        hostname=agent.hostname,
        os=agent.os,
        arch=agent.arch,
        version=agent.version,
        online=online,
        last_seen_at=agent.last_seen_at,
        latest_metrics=metric_view,
        service_counts=counts,
        service_kind_counts=kind_counts,
        service_problem_count=int(problem_count or 0),
    )


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)
) -> list[AgentSummary]:
    agents = (await session.scalars(select(Agent).order_by(Agent.name))).all()
    return [
        await build_summary(agent, session, settings.agent_offline_after_seconds)
        for agent in agents
    ]


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AgentDetail:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    summary = await build_summary(agent, session, settings.agent_offline_after_seconds)
    services = (
        await session.scalars(
            select(ServiceStatus)
            .where(ServiceStatus.agent_id == agent.id)
            .order_by(ServiceStatus.kind, ServiceStatus.name)
        )
    ).all()
    return AgentDetail(
        **summary.model_dump(),
        capabilities=agent.capabilities,
        services=[
            ServiceView(
                kind=item.kind,
                key=item.service_key,
                name=item.name,
                state=item.state,
                detail=item.detail,
                healthy=item.healthy,
                observed_at=item.observed_at,
            )
            for item in services
        ],
    )


@router.get("/events", response_model=list[AlertEventView])
async def list_events(
    event_status: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|firing|acknowledged|silenced|resolved)$",
    ),
    session: AsyncSession = Depends(get_session),
) -> list[AlertEventView]:
    query = select(AlertEvent).order_by(AlertEvent.last_observed_at.desc()).limit(200)
    if event_status:
        query = query.where(AlertEvent.status == event_status)
    events = (await session.scalars(query)).all()
    return [
        AlertEventView(
            id=event.id,
            agent_id=event.agent_id,
            source=event.source,
            service_kind=event.service_kind,
            service_key=event.service_key,
            title=event.title,
            severity=event.severity,
            status=event.status,
            observation_count=event.observation_count,
            detail=event.detail,
            first_observed_at=event.first_observed_at,
            last_observed_at=event.last_observed_at,
            firing_at=event.firing_at,
            acknowledged_at=event.acknowledged_at,
            silenced_until=event.silenced_until,
            resolved_at=event.resolved_at,
        )
        for event in events
    ]


@router.post(
    "/events/{event_id}/actions",
    response_model=AlertEventView,
    dependencies=[Depends(require_admin)],
)
async def act_on_event(
    event_id: str,
    payload: AlertEventAction,
    session: AsyncSession = Depends(get_session),
) -> AlertEventView:
    event = await session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    if event.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="resolved event cannot be acknowledged or silenced",
        )
    current_time = now_utc()
    if payload.action == "acknowledge":
        event.status = "acknowledged"
        event.acknowledged_at = current_time
        event.silenced_until = None
    else:
        event.status = "silenced"
        event.silenced_until = current_time + timedelta(minutes=payload.silence_minutes)
    await session.commit()
    return AlertEventView(
        id=event.id,
        agent_id=event.agent_id,
        source=event.source,
        service_kind=event.service_kind,
        service_key=event.service_key,
        title=event.title,
        severity=event.severity,
        status=event.status,
        observation_count=event.observation_count,
        detail=event.detail,
        first_observed_at=event.first_observed_at,
        last_observed_at=event.last_observed_at,
        firing_at=event.firing_at,
        acknowledged_at=event.acknowledged_at,
        silenced_until=event.silenced_until,
        resolved_at=event.resolved_at,
    )
