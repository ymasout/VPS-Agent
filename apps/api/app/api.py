from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_session
from .models import Agent, MetricSnapshot, RegistrationToken, ServiceStatus
from .schemas import (
    AgentDetail,
    AgentRegister,
    AgentRegistered,
    AgentReport,
    AgentSummary,
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
    payload: AgentRegister, session: AsyncSession = Depends(get_session)
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
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="machine is already registered"
        )
    credential = generate_token("agt")
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
    token.used_at = current_time
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return AgentRegistered(agent_id=agent.id, credential=credential)


@router.post("/agents/report", response_model=ReportReceipt)
async def report_agent(
    payload: AgentReport,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> ReportReceipt:
    received_at = now_utc()
    agent.hostname = payload.hostname
    agent.version = payload.version
    agent.capabilities = payload.capabilities
    agent.last_seen_at = received_at
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
    await session.commit()
    return ReportReceipt(received_at=received_at)


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
            ServiceStatus.healthy.is_(False)
            | ServiceStatus.state.in_(["failed", "unhealthy"]),
        )
    )
    online = bool(
        agent.last_seen_at and agent.last_seen_at >= now_utc() - timedelta(seconds=offline_after)
    )
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
