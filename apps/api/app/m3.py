from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import current_agent, now_utc, require_admin
from .config import Settings, get_settings
from .database import get_session
from .diagnostics import (
    add_evidence,
    collect_control_plane_evidence,
    finalize_diagnostic,
    reclaim_stale_diagnostics,
    run_diagnostic,
)
from .models import (
    Agent,
    AgentEvidenceSource,
    AlertEvent,
    DeploymentVersion,
    DiagnosticRun,
    EvidenceItem,
    EvidenceRequest,
    InstanceLogSource,
    ManagedService,
    Repository,
    ServiceInstance,
    ServiceStatus,
)
from .schemas import (
    AlertEventView,
    DiagnosticResult,
    DiagnosticView,
    EvidenceRequestClaim,
    EvidenceRequestComplete,
    EvidenceRequestReceipt,
    EvidenceRequestWork,
    EvidenceView,
    ServiceMappingCreate,
    ServiceMappingView,
)

router = APIRouter(prefix="/api/v1")


def event_view(event: AlertEvent) -> AlertEventView:
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


async def diagnostic_view(session: AsyncSession, diagnostic: DiagnosticRun) -> DiagnosticView:
    evidence = list(
        (
            await session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.diagnostic_id == diagnostic.id)
                .order_by(EvidenceItem.collected_at, EvidenceItem.id)
            )
        ).all()
    )
    return DiagnosticView(
        id=diagnostic.id,
        event_id=diagnostic.event_id,
        instance_id=diagnostic.instance_id,
        status=diagnostic.status,
        trigger=diagnostic.trigger,
        provider=diagnostic.provider,
        result=DiagnosticResult.model_validate(diagnostic.result) if diagnostic.result else None,
        error_code=diagnostic.error_code,
        error_detail=diagnostic.error_detail,
        evidence=[
            EvidenceView(
                id=item.id,
                evidence_type=item.evidence_type,
                source_label=item.source_label,
                content=item.content,
                redacted=item.redacted,
                truncated=item.truncated,
                collected_at=item.collected_at,
                source_metadata=item.source_metadata,
            )
            for item in evidence
        ],
        created_at=diagnostic.created_at,
        started_at=diagnostic.started_at,
        completed_at=diagnostic.completed_at,
    )


@router.post(
    "/service-mappings",
    response_model=ServiceMappingView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_service_mapping(
    payload: ServiceMappingCreate,
    session: AsyncSession = Depends(get_session),
) -> ServiceMappingView:
    agent = await session.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if payload.service_kind != "docker":
        raise HTTPException(status_code=409, detail="first diagnostic slice supports Docker only")
    duplicate = await session.scalar(
        select(ServiceInstance).where(
            ServiceInstance.agent_id == payload.agent_id,
            ServiceInstance.service_kind == payload.service_kind,
            ServiceInstance.service_key == payload.service_key,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="service instance is already mapped")
    observed = await session.scalar(
        select(ServiceStatus).where(
            ServiceStatus.agent_id == payload.agent_id,
            ServiceStatus.kind == payload.service_kind,
            ServiceStatus.service_key == payload.service_key,
        )
    )
    if observed is None:
        raise HTTPException(status_code=409, detail="service has not been observed by this agent")
    advertised_source = await session.scalar(
        select(AgentEvidenceSource).where(
            AgentEvidenceSource.agent_id == payload.agent_id,
            AgentEvidenceSource.source_key == payload.log_source_key,
        )
    )
    if advertised_source is None or advertised_source.kind != "docker_logs":
        raise HTTPException(status_code=409, detail="log source is not in the agent allowlist")

    managed = ManagedService(
        name=payload.name,
        environment=payload.environment,
        description=payload.description,
    )
    session.add(managed)
    await session.flush()
    instance = ServiceInstance(
        service_id=managed.id,
        agent_id=payload.agent_id,
        service_kind=payload.service_kind,
        service_key=payload.service_key,
        deployment_directory=payload.deployment_directory,
    )
    session.add(instance)
    await session.flush()
    session.add(
        InstanceLogSource(
            instance_id=instance.id,
            source_key=payload.log_source_key,
            kind=advertised_source.kind,
            display_name=advertised_source.display_name,
        )
    )
    repository = None
    if payload.repository_full_name:
        repository = await session.scalar(
            select(Repository).where(Repository.full_name == payload.repository_full_name)
        )
        if repository is None:
            repository = Repository(
                full_name=payload.repository_full_name,
                default_branch=payload.default_branch,
            )
            session.add(repository)
            await session.flush()
    if payload.commit_sha or payload.image_digest or repository:
        session.add(
            DeploymentVersion(
                instance_id=instance.id,
                repository_id=repository.id if repository else None,
                commit_sha=payload.commit_sha,
                image_digest=payload.image_digest,
            )
        )
    await session.commit()
    return ServiceMappingView(
        service_id=managed.id,
        instance_id=instance.id,
        name=managed.name,
        environment=managed.environment,
        agent_id=instance.agent_id,
        service_kind=instance.service_kind,
        service_key=instance.service_key,
        deployment_directory=instance.deployment_directory,
        log_source_key=payload.log_source_key,
        repository_full_name=repository.full_name if repository else None,
        commit_sha=payload.commit_sha,
        image_digest=payload.image_digest,
    )


@router.get("/events/{event_id}", response_model=AlertEventView)
async def get_event(
    event_id: str, session: AsyncSession = Depends(get_session)
) -> AlertEventView:
    event = await session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event_view(event)


@router.post(
    "/events/{event_id}/diagnostics",
    response_model=DiagnosticView,
    dependencies=[Depends(require_admin)],
)
async def trigger_diagnostic(
    event_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DiagnosticView:
    reclaimed = await reclaim_stale_diagnostics(session, settings)
    event = await session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    if event.source != "service" or not event.service_kind or not event.service_key:
        raise HTTPException(status_code=409, detail="event does not map to a service instance")
    instance = await session.scalar(
        select(ServiceInstance).where(
            ServiceInstance.agent_id == event.agent_id,
            ServiceInstance.service_kind == event.service_kind,
            ServiceInstance.service_key == event.service_key,
        )
    )
    if instance is None:
        raise HTTPException(status_code=409, detail="service instance mapping is required")
    active_key = f"event:{event.id}"
    existing = await session.scalar(
        select(DiagnosticRun).where(DiagnosticRun.active_key == active_key)
    )
    if existing:
        if reclaimed:
            await session.commit()
            for diagnostic_id in reclaimed:
                background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
        return await diagnostic_view(session, existing)

    diagnostic = DiagnosticRun(
        event_id=event.id,
        instance_id=instance.id,
        active_key=active_key,
        status="pending",
        trigger="manual",
        provider=settings.diagnostic_provider,
    )
    try:
        async with session.begin_nested():
            session.add(diagnostic)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(DiagnosticRun).where(DiagnosticRun.active_key == active_key)
        )
        if existing is None:
            raise
        return await diagnostic_view(session, existing)
    await collect_control_plane_evidence(session, diagnostic, event, instance)
    sources = list(
        (
            await session.scalars(
                select(InstanceLogSource).where(
                    InstanceLogSource.instance_id == instance.id,
                    InstanceLogSource.enabled.is_(True),
                )
            )
        ).all()
    )
    for source in sources:
        session.add(
            EvidenceRequest(
                diagnostic_id=diagnostic.id,
                agent_id=instance.agent_id,
                log_source_id=source.id,
                source_key=source.source_key,
                since_at=event.last_observed_at
                - timedelta(seconds=settings.diagnostic_log_lookback_seconds),
                until_at=now_utc(),
                max_lines=min(settings.diagnostic_max_log_lines, 500),
                max_bytes=min(settings.diagnostic_max_log_bytes, 65536),
                timeout_seconds=min(settings.diagnostic_collection_timeout_seconds, 15),
            )
        )
    await session.flush()
    if not sources:
        await finalize_diagnostic(session, diagnostic, settings)
    await session.commit()
    for diagnostic_id in reclaimed:
        background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
    return await diagnostic_view(session, diagnostic)


@router.get("/events/{event_id}/diagnostics", response_model=list[DiagnosticView])
async def list_event_diagnostics(
    event_id: str, session: AsyncSession = Depends(get_session)
) -> list[DiagnosticView]:
    diagnostics = list(
        (
            await session.scalars(
                select(DiagnosticRun)
                .where(DiagnosticRun.event_id == event_id)
                .order_by(DiagnosticRun.created_at.desc())
            )
        ).all()
    )
    return [await diagnostic_view(session, item) for item in diagnostics]


@router.get("/diagnostics/{diagnostic_id}", response_model=DiagnosticView)
async def get_diagnostic(
    diagnostic_id: str, session: AsyncSession = Depends(get_session)
) -> DiagnosticView:
    diagnostic = await session.get(DiagnosticRun, diagnostic_id)
    if diagnostic is None:
        raise HTTPException(status_code=404, detail="diagnostic not found")
    return await diagnostic_view(session, diagnostic)


@router.get("/agents/evidence-requests/next", response_model=EvidenceRequestClaim)
async def claim_evidence_request(
    background_tasks: BackgroundTasks,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceRequestClaim:
    reclaimed = await reclaim_stale_diagnostics(session, settings)
    stale_before = now_utc() - timedelta(seconds=settings.diagnostic_request_claim_seconds)
    request = await session.scalar(
        select(EvidenceRequest)
        .where(
            EvidenceRequest.agent_id == agent.id,
            or_(
                EvidenceRequest.status == "pending",
                (EvidenceRequest.status == "claimed")
                & (EvidenceRequest.claimed_at <= stale_before),
            ),
        )
        .order_by(EvidenceRequest.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if request is None:
        if reclaimed:
            await session.commit()
            for diagnostic_id in reclaimed:
                background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
        return EvidenceRequestClaim()
    request.status = "claimed"
    request.claimed_at = now_utc()
    await session.commit()
    for diagnostic_id in reclaimed:
        background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
    return EvidenceRequestClaim(
        request=EvidenceRequestWork(
            id=request.id,
            source_key=request.source_key,
            since_at=request.since_at,
            until_at=request.until_at,
            max_lines=request.max_lines,
            max_bytes=request.max_bytes,
            timeout_seconds=request.timeout_seconds,
        )
    )


@router.post(
    "/agents/evidence-requests/{request_id}/complete", response_model=EvidenceRequestReceipt
)
async def complete_evidence_request(
    request_id: str,
    payload: EvidenceRequestComplete,
    background_tasks: BackgroundTasks,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceRequestReceipt:
    reclaimed = await reclaim_stale_diagnostics(session, settings)
    request = await session.get(EvidenceRequest, request_id)
    if request is None or request.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="evidence request not found")
    diagnostic = await session.get(DiagnosticRun, request.diagnostic_id)
    if diagnostic is None:
        raise HTTPException(status_code=404, detail="diagnostic not found")
    if request.status in {"completed", "failed"}:
        if reclaimed:
            await session.commit()
            for diagnostic_id in reclaimed:
                background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
        return EvidenceRequestReceipt(
            diagnostic_id=diagnostic.id, diagnostic_status=diagnostic.status
        )
    request.status = payload.status
    request.completed_at = now_utc()
    request.error = payload.error
    if payload.status == "completed":
        await add_evidence(
            session,
            diagnostic.id,
            "docker_logs",
            f"受限日志源 {request.source_key}",
            payload.content,
            payload.collected_at,
            request_id=request.id,
            truncated=payload.truncated,
            source_metadata={
                "source_key": request.source_key,
                "agent_redacted": payload.redacted,
                "since_at": request.since_at.isoformat(),
                "until_at": request.until_at.isoformat(),
                "max_lines": request.max_lines,
                "max_bytes": request.max_bytes,
            },
            max_bytes=request.max_bytes,
            max_lines=request.max_lines,
        )
    await session.flush()
    remaining = await session.scalar(
        select(func.count())
        .select_from(EvidenceRequest)
        .where(
            EvidenceRequest.diagnostic_id == diagnostic.id,
            EvidenceRequest.status.in_(["pending", "claimed"]),
        )
    )
    should_run = not remaining
    if should_run:
        diagnostic.status = "running"
        diagnostic.started_at = now_utc()
    await session.commit()
    scheduled = set(reclaimed)
    if should_run:
        scheduled.add(diagnostic.id)
    for diagnostic_id in scheduled:
        background_tasks.add_task(run_diagnostic, diagnostic_id, settings)
    return EvidenceRequestReceipt(
        diagnostic_id=diagnostic.id, diagnostic_status=diagnostic.status
    )
