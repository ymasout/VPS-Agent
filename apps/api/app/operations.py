import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import agent_is_online, current_agent, now_utc, require_admin
from .config import Settings, get_settings
from .database import get_session, session_factory
from .image_refs import parse_digest_reference
from .models import (
    Agent,
    AgentDeploymentCandidate,
    AgentOperationCapability,
    AlertEvent,
    DiagnosticRun,
    ManagedService,
    Operation,
    OperationTransition,
    ServiceInstance,
    ServiceStatus,
)
from .redaction import redact_text, truncate_lines, truncate_utf8
from .schemas import (
    AgentReport,
    DeploymentOperationTask,
    DeploymentPlanCreate,
    DeployPolicyUpdate,
    DeployPolicyView,
    OperationClaim,
    OperationConfirm,
    OperationExecutionResult,
    OperationPlanCreate,
    OperationReceipt,
    OperationRollbackCreate,
    OperationTask,
    OperationTransitionView,
    OperationView,
)
from .security import sign_operation

router = APIRouter(prefix="/api/v1")
RESTART_ACTION = "docker_restart"
DEPLOY_ACTION = "docker_compose_deploy"
DEPLOY_PLAN_VERSION = "m4.2b-executable-v1"
ROLLBACK_PLAN_VERSION = "m4.2c-rollback-v1"

ACTIVE_STATUSES = {
    "planned",
    "prechecking",
    "awaiting_confirmation",
    "queued",
    "claimed",
    "running",
    "verifying",
}
PRE_EXECUTION_STATUSES = {
    "planned",
    "prechecking",
    "awaiting_confirmation",
    "queued",
    "claimed",
}
ALLOWED_TRANSITIONS = {
    "planned": {"prechecking", "expired"},
    "prechecking": {"awaiting_confirmation", "failed", "expired"},
    "awaiting_confirmation": {"queued", "failed", "canceled", "expired"},
    "queued": {"claimed", "failed", "canceled", "expired"},
    "claimed": {"claimed", "running", "failed", "expired"},
    "running": {"verifying", "failed"},
    "verifying": {"succeeded", "failed"},
}


@router.get("/agents/operations/healthz")
async def operation_route_health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-operations"}


def task_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def signing_fields(operation: Operation, instance: ServiceInstance) -> list[str]:
    if not all(
        (
            operation.issued_at,
            operation.task_nonce,
            operation.signing_key_id,
        )
    ):
        raise ValueError("operation task is incomplete")
    return [
        "v1",
        operation.id,
        operation.action_type,
        operation.agent_id,
        instance.service_kind,
        instance.service_key,
        task_time(operation.issued_at),
        task_time(operation.expires_at),
        operation.idempotency_key,
        str(operation.attempt),
        operation.task_nonce,
        operation.signing_key_id,
    ]


def deployment_signing_fields(operation: Operation, instance: ServiceInstance) -> list[str]:
    if not all(
        (
            operation.issued_at,
            operation.task_nonce,
            operation.signing_key_id,
            operation.current_digest,
            operation.target_digest,
        )
    ):
        raise ValueError("deployment task is incomplete")
    return [
        "v2",
        operation.id,
        operation.action_type,
        operation.agent_id,
        instance.service_kind,
        instance.service_key,
        operation.current_digest,
        operation.target_digest,
        task_time(operation.issued_at),
        task_time(operation.expires_at),
        operation.idempotency_key,
        str(operation.attempt),
        operation.task_nonce,
        operation.signing_key_id,
    ]


async def transition(
    session: AsyncSession,
    operation: Operation,
    to_status: str,
    actor_type: str,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    previous = operation.status
    if to_status not in ALLOWED_TRANSITIONS.get(previous, set()):
        raise ValueError(f"invalid operation transition: {previous} -> {to_status}")
    operation.status = to_status
    if to_status not in ACTIVE_STATUSES:
        operation.active_key = None
        operation.completed_at = now_utc()
    session.add(
        OperationTransition(
            operation_id=operation.id,
            from_status=previous,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            details=details or {},
        )
    )


def stale_operation_outcome(
    operation: Operation, settings: Settings, observed_at: datetime
) -> tuple[str, str, str] | None:
    """Return a conservative terminal outcome only when this state is actually stale."""
    if operation.status == "running":
        if operation.lease_expires_at is None or operation.lease_expires_at <= observed_at:
            return (
                "failed",
                "execution_outcome_unknown",
                "Agent stopped reporting after execution started; task was not replayed",
            )
        return None
    if operation.status == "verifying":
        if operation.execution_completed_at is None:
            return (
                "failed",
                "invalid_operation_state",
                "verification state is missing the execution completion time",
            )
        deadline = operation.execution_completed_at + timedelta(
            seconds=settings.operation_verification_timeout_seconds
        )
        if deadline <= observed_at:
            return "failed", "verification_timeout", "health verification timed out"
        return None
    if operation.status in PRE_EXECUTION_STATUSES and operation.expires_at <= observed_at:
        return "expired", "expired", "operation task expired"
    return None


async def operation_view(session: AsyncSession, operation: Operation) -> OperationView:
    timeline = list(
        (
            await session.scalars(
                select(OperationTransition)
                .where(OperationTransition.operation_id == operation.id)
                .order_by(OperationTransition.created_at, OperationTransition.id)
            )
        ).all()
    )
    return OperationView(
        **{
            field: getattr(operation, field)
            for field in OperationView.model_fields
            if field != "transitions"
        },
        transitions=[
            OperationTransitionView(
                from_status=item.from_status,
                to_status=item.to_status,
                actor_type=item.actor_type,
                actor_id=item.actor_id,
                reason=item.reason,
                details=item.details,
                created_at=item.created_at,
            )
            for item in timeline
        ],
    )


def require_executable_action(operation: Operation) -> None:
    if operation.action_type == RESTART_ACTION:
        return
    if operation.action_type == DEPLOY_ACTION:
        plan_version = operation.plan_snapshot.get("plan_version")
        is_original_deploy = plan_version == DEPLOY_PLAN_VERSION and operation.rollback_of is None
        is_rollback = plan_version == ROLLBACK_PLAN_VERSION and operation.rollback_of is not None
        if (
            (is_original_deploy or is_rollback)
            and operation.plan_snapshot.get("permanently_non_executable") is not True
            and operation.current_digest
            and operation.target_digest
        ):
            return
    raise HTTPException(
        status_code=409,
        detail="plan-only deployment is permanently non-executable or has an unsupported version",
    )


async def resolve_instance(
    session: AsyncSession, payload: OperationPlanCreate
) -> tuple[ServiceInstance, AlertEvent | None, DiagnosticRun | None]:
    event = await session.get(AlertEvent, payload.event_id) if payload.event_id else None
    diagnostic = (
        await session.get(DiagnosticRun, payload.diagnostic_id) if payload.diagnostic_id else None
    )
    if payload.event_id and event is None:
        raise HTTPException(status_code=404, detail="event not found")
    if payload.diagnostic_id and diagnostic is None:
        raise HTTPException(status_code=404, detail="diagnostic not found")
    instance_id = payload.instance_id
    if diagnostic:
        if payload.event_id and diagnostic.event_id != payload.event_id:
            raise HTTPException(status_code=409, detail="diagnostic does not belong to event")
        instance_id = instance_id or diagnostic.instance_id
    if event:
        if event.source != "service" or not event.service_kind or not event.service_key:
            raise HTTPException(status_code=409, detail="event does not identify a service")
        event_instance = await session.scalar(
            select(ServiceInstance).where(
                ServiceInstance.agent_id == event.agent_id,
                ServiceInstance.service_kind == event.service_kind,
                ServiceInstance.service_key == event.service_key,
            )
        )
        if event_instance is None:
            raise HTTPException(status_code=409, detail="event service is not mapped")
        if instance_id and instance_id != event_instance.id:
            raise HTTPException(status_code=409, detail="instance does not belong to event")
        instance_id = event_instance.id
    if not instance_id:
        raise HTTPException(status_code=422, detail="instance_id or service event is required")
    instance = await session.get(ServiceInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="service instance not found")
    if diagnostic and diagnostic.instance_id != instance.id:
        raise HTTPException(status_code=409, detail="diagnostic does not belong to instance")
    return instance, event, diagnostic


async def run_prechecks(
    session: AsyncSession,
    instance: ServiceInstance,
    settings: Settings,
    current_time: datetime,
) -> tuple[dict, Agent, ManagedService, ServiceStatus | None]:
    agent = await session.get(Agent, instance.agent_id)
    managed = await session.get(ManagedService, instance.service_id)
    observed = await session.scalar(
        select(ServiceStatus).where(
            ServiceStatus.agent_id == instance.agent_id,
            ServiceStatus.kind == instance.service_kind,
            ServiceStatus.service_key == instance.service_key,
        )
    )
    capability = await session.scalar(
        select(AgentOperationCapability).where(
            AgentOperationCapability.agent_id == instance.agent_id,
            AgentOperationCapability.action_type == "docker_restart",
            AgentOperationCapability.service_kind == instance.service_kind,
            AgentOperationCapability.service_key == instance.service_key,
        )
    )
    checks = {
        "agent_online": bool(
            agent
            and agent_is_online(
                agent.last_seen_at, current_time, settings.agent_offline_after_seconds
            )
        ),
        "docker_instance": instance.service_kind == "docker",
        "mapping_valid": managed is not None and observed is not None,
        "agent_write_capability": capability is not None,
        "control_plane_permission": instance.restart_enabled,
        "non_critical_service": bool(managed and managed.criticality == "non_critical"),
        "observation_fresh": bool(
            observed
            and observed.observed_at
            >= current_time - timedelta(seconds=settings.operation_observation_max_age_seconds)
        ),
    }
    checks["passed"] = all(checks.values())
    if agent is None or managed is None:
        raise HTTPException(status_code=409, detail="service mapping is incomplete")
    return checks, agent, managed, observed


async def build_restart_plan(
    session: AsyncSession,
    instance: ServiceInstance,
    event: AlertEvent | None,
    diagnostic: DiagnosticRun | None,
    settings: Settings,
    *,
    expires_in_seconds: int,
    source_metadata: dict | None = None,
) -> Operation:
    """Build one restart plan while preserving the M4 prechecks and state ceiling."""

    current_time = now_utc()
    checks, agent, managed, observed = await run_prechecks(
        session, instance, settings, current_time
    )
    source_metadata = source_metadata or {}
    conversation_source = source_metadata.get("conversation_source")
    plan_snapshot = {
        "machine": {"id": agent.id, "name": agent.name, "hostname": agent.hostname},
        "service": {
            "id": managed.id,
            "name": managed.name,
            "environment": managed.environment,
            "instance_id": instance.id,
            "service_kind": instance.service_kind,
            "service_key": instance.service_key,
        },
        "action_type": "docker_restart",
        "risk_level": "medium",
        "impact": "单服务短暂不可用；不修改镜像、配置、路径或仓库。",
        "observed_state": observed.state if observed else None,
    }
    if conversation_source is not None:
        plan_snapshot["conversation_source"] = conversation_source
    operation = Operation(
        organization_id=source_metadata.get(
            "organization_id",
            "local",
        ),
        instance_id=instance.id,
        agent_id=agent.id,
        source_event_id=event.id if event else None,
        source_diagnostic_id=diagnostic.id if diagnostic else None,
        source_conversation_turn_id=source_metadata.get("turn_id"),
        conversation_request_id=source_metadata.get("conversation_request_id"),
        action_type=RESTART_ACTION,
        status="planned",
        active_key=f"{instance.id}:write",
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="单个非关键 Docker 服务会短暂中断并重新启动。",
        plan_snapshot=plan_snapshot,
        precheck_result=checks,
        verification_policy={
            "kind": "fresh_service_observation",
            "requires_healthy": True,
            "required_state": "running",
            "stability_seconds": settings.operation_verification_window_seconds,
            "timeout_seconds": settings.operation_verification_timeout_seconds,
        },
        idempotency_key="op_" + secrets.token_urlsafe(24),
        expires_at=current_time + timedelta(seconds=expires_in_seconds),
    )
    async with session.begin_nested():
        session.add(operation)
        await session.flush()
        session.add(
            OperationTransition(
                operation_id=operation.id,
                from_status=None,
                to_status="planned",
                actor_type="admin",
                actor_id="local-admin",
                reason=source_metadata.get("reason", "restart plan requested"),
                details=source_metadata.get("transition_details", {"source": "web"}),
            )
        )
        await transition(session, operation, "prechecking", "control_plane")
        if checks["passed"]:
            await transition(session, operation, "awaiting_confirmation", "control_plane")
        else:
            operation.error_code = "precheck_failed"
            operation.error_detail = "one or more safety prechecks failed"
            await transition(
                session,
                operation,
                "failed",
                "control_plane",
                reason=operation.error_detail,
            )
    await session.commit()
    return operation


async def run_deploy_prechecks(
    session: AsyncSession,
    instance: ServiceInstance,
    settings: Settings,
    current_time: datetime,
    *,
    expected_current_digest: str | None = None,
    target_digest: str,
    require_current_healthy: bool = True,
) -> tuple[dict, Agent, ManagedService, ServiceStatus | None, AgentDeploymentCandidate]:
    agent = await session.get(Agent, instance.agent_id)
    managed = await session.get(ManagedService, instance.service_id)
    observed = await session.scalar(
        select(ServiceStatus).where(
            ServiceStatus.agent_id == instance.agent_id,
            ServiceStatus.kind == instance.service_kind,
            ServiceStatus.service_key == instance.service_key,
        )
    )
    candidate = await session.scalar(
        select(AgentDeploymentCandidate).where(
            AgentDeploymentCandidate.agent_id == instance.agent_id,
            AgentDeploymentCandidate.service_kind == instance.service_kind,
            AgentDeploymentCandidate.service_key == instance.service_key,
        )
    )
    capability = await session.scalar(
        select(AgentOperationCapability).where(
            AgentOperationCapability.agent_id == instance.agent_id,
            AgentOperationCapability.action_type == DEPLOY_ACTION,
            AgentOperationCapability.service_kind == instance.service_kind,
            AgentOperationCapability.service_key == instance.service_key,
        )
    )
    if agent is None or managed is None or candidate is None:
        raise HTTPException(status_code=409, detail="deployment mapping is incomplete")
    target_repository, canonical_target = parse_digest_reference(target_digest)
    checks: dict[str, bool] = {
        "agent_online": agent_is_online(
            agent.last_seen_at, current_time, settings.agent_offline_after_seconds
        ),
        "docker_instance": instance.service_kind == "docker",
        "mapping_valid": observed is not None,
        "agent_write_capability": capability is not None,
        "control_plane_permission": instance.deploy_enabled,
        "non_critical_service": managed.criticality == "non_critical",
        "candidate_eligible": bool(
            candidate.eligible and candidate.repository and candidate.current_digest
        ),
        "observation_fresh": candidate.observed_at
        >= current_time - timedelta(seconds=settings.operation_observation_max_age_seconds),
        "same_repository": bool(
            canonical_target == target_digest
            and candidate.repository
            and target_repository == candidate.repository
        ),
        "different_digest": candidate.current_digest != target_digest,
        "current_digest_unchanged": bool(
            expected_current_digest is None or candidate.current_digest == expected_current_digest
        ),
    }
    if require_current_healthy:
        checks["service_running"] = bool(observed and observed.state == "running")
        checks["service_healthy"] = bool(observed and observed.healthy is True)
    else:
        checks["recovery_source_observed"] = observed is not None
    checks["passed"] = all(checks.values())
    return checks, agent, managed, observed, candidate


def is_rollback_source(operation: Operation | None) -> bool:
    return bool(
        operation
        and operation.action_type == DEPLOY_ACTION
        and operation.plan_snapshot.get("plan_version") == DEPLOY_PLAN_VERSION
        and operation.rollback_of is None
        and operation.status == "failed"
        and operation.started_at is not None
        and operation.current_digest
        and operation.target_digest
    )


async def run_rollback_prechecks(
    session: AsyncSession,
    source: Operation | None,
    instance: ServiceInstance,
    settings: Settings,
    current_time: datetime,
) -> tuple[
    dict,
    Agent | None,
    ManagedService | None,
    ServiceStatus | None,
    AgentDeploymentCandidate | None,
]:
    if not is_rollback_source(source):
        return (
            {"rollback_source_valid": False, "passed": False},
            None,
            None,
            None,
            None,
        )
    assert source is not None and source.current_digest and source.target_digest
    checks, agent, managed, observed, candidate = await run_deploy_prechecks(
        session,
        instance,
        settings,
        current_time,
        expected_current_digest=source.target_digest,
        target_digest=source.current_digest,
        require_current_healthy=False,
    )
    checks.update(
        {
            "rollback_source_valid": True,
            "rollback_source_failed": source.status == "failed",
            "rollback_source_execution_started": source.started_at is not None,
            "rollback_target_frozen": candidate.current_digest == source.target_digest,
        }
    )
    checks["passed"] = all(value for name, value in checks.items() if name != "passed")
    return checks, agent, managed, observed, candidate


@router.post(
    "/operations",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_operation(
    payload: OperationPlanCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    if payload.action_type != RESTART_ACTION:
        raise HTTPException(status_code=422, detail="unsupported operation action")
    instance, event, diagnostic = await resolve_instance(session, payload)
    try:
        operation = await build_restart_plan(
            session,
            instance,
            event,
            diagnostic,
            settings,
            expires_in_seconds=payload.expires_in_seconds,
        )
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="another write operation is active for this service"
        ) from error
    return await operation_view(session, operation)


@router.post(
    "/deployment-plans",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_deployment_plan(
    payload: DeploymentPlanCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    """Persist an M4.2a snapshot which is permanently non-executable."""

    current_time = now_utc()
    instance = await session.get(ServiceInstance, payload.instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="service instance not found")
    agent = await session.get(Agent, instance.agent_id)
    managed = await session.get(ManagedService, instance.service_id)
    if agent is None or managed is None:
        raise HTTPException(status_code=409, detail="service mapping is incomplete")
    candidate = await session.scalar(
        select(AgentDeploymentCandidate).where(
            AgentDeploymentCandidate.agent_id == instance.agent_id,
            AgentDeploymentCandidate.service_kind == instance.service_kind,
            AgentDeploymentCandidate.service_key == instance.service_key,
        )
    )
    observed = await session.scalar(
        select(ServiceStatus).where(
            ServiceStatus.agent_id == instance.agent_id,
            ServiceStatus.kind == instance.service_kind,
            ServiceStatus.service_key == instance.service_key,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=409, detail="deployment candidate is not reported")
    if not candidate.eligible or not candidate.repository or not candidate.current_digest:
        raise HTTPException(
            status_code=409,
            detail=f"deployment candidate is ineligible: {candidate.reason_code or 'unknown'}",
        )
    target_repository, canonical_target = parse_digest_reference(payload.target_digest)
    if canonical_target != payload.target_digest or target_repository != candidate.repository:
        raise HTTPException(status_code=409, detail="target image must use the current repository")
    if payload.target_digest == candidate.current_digest:
        raise HTTPException(status_code=409, detail="target digest must differ from current digest")
    checks = {
        "agent_online": agent_is_online(
            agent.last_seen_at, current_time, settings.agent_offline_after_seconds
        ),
        "docker_instance": instance.service_kind == "docker",
        "mapping_valid": True,
        "service_observed": observed is not None,
        "service_running": bool(observed and observed.state == "running"),
        "service_healthy": bool(observed and observed.healthy is True),
        "candidate_eligible": candidate.eligible,
        "non_critical_service": managed.criticality == "non_critical",
        "observation_fresh": candidate.observed_at
        >= current_time - timedelta(seconds=settings.operation_observation_max_age_seconds),
        "same_repository": True,
        "different_digest": True,
    }
    checks["passed"] = all(checks.values())
    if not checks["passed"]:
        failed = [name for name, passed in checks.items() if name != "passed" and not passed]
        raise HTTPException(
            status_code=409,
            detail="deployment plan rejected: " + ", ".join(failed),
        )
    operation = Operation(
        instance_id=instance.id,
        agent_id=agent.id,
        action_type=DEPLOY_ACTION,
        status="planned",
        active_key=None,
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="Read-only deployment preview; this plan can never execute.",
        plan_snapshot={
            "plan_version": "m4.2a-plan-only-v1",
            "execution_policy": "none",
            "permanently_non_executable": True,
            "machine": {"id": agent.id, "name": agent.name, "hostname": agent.hostname},
            "service": {
                "id": managed.id,
                "name": managed.name,
                "environment": managed.environment,
                "instance_id": instance.id,
                "service_kind": instance.service_kind,
                "service_key": instance.service_key,
            },
            "repository": candidate.repository,
            "current_digest": candidate.current_digest,
            "target_digest": payload.target_digest,
            "candidate_observed_at": candidate.observed_at.isoformat(),
            "observed_state": observed.state if observed else None,
            "observed_healthy": observed.healthy if observed else None,
        },
        precheck_result=checks,
        verification_policy={
            "kind": "future_digest_and_health_verification",
            "required_state": "running",
            "requires_healthy": True,
            "requires_target_digest": True,
            "execution_available": False,
        },
        idempotency_key="plan_" + secrets.token_urlsafe(24),
        expires_at=current_time + timedelta(seconds=payload.expires_in_seconds),
    )
    session.add(operation)
    await session.flush()
    session.add(
        OperationTransition(
            operation_id=operation.id,
            from_status=None,
            to_status="planned",
            actor_type="admin",
            actor_id="local-admin",
            reason="read-only deployment plan created",
            details={"plan_only": True, "executable": False},
        )
    )
    await session.commit()
    return await operation_view(session, operation)


@router.post(
    "/service-instances/{instance_id}/deploy-policy",
    response_model=DeployPolicyView,
    dependencies=[Depends(require_admin)],
)
async def update_deploy_policy(
    instance_id: str,
    payload: DeployPolicyUpdate,
    session: AsyncSession = Depends(get_session),
) -> DeployPolicyView:
    instance = await session.get(ServiceInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="service instance not found")
    managed = await session.get(ManagedService, instance.service_id)
    capability = await session.scalar(
        select(AgentOperationCapability).where(
            AgentOperationCapability.agent_id == instance.agent_id,
            AgentOperationCapability.action_type == DEPLOY_ACTION,
            AgentOperationCapability.service_kind == instance.service_kind,
            AgentOperationCapability.service_key == instance.service_key,
        )
    )
    if managed is None:
        raise HTTPException(status_code=409, detail="service mapping is incomplete")
    if payload.enabled and (instance.service_kind != "docker" or capability is None):
        raise HTTPException(status_code=409, detail="agent has not enabled Compose deployment")
    if payload.enabled and payload.criticality != "non_critical":
        raise HTTPException(
            status_code=409, detail="deployment is limited to non-critical services"
        )
    instance.deploy_enabled = payload.enabled
    managed.criticality = payload.criticality
    await session.commit()
    return DeployPolicyView(
        instance_id=instance.id,
        deploy_enabled=instance.deploy_enabled,
        criticality=managed.criticality,
    )


@router.post(
    "/deployment-operations",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_deployment_operation(
    payload: DeploymentPlanCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    current_time = now_utc()
    instance = await session.get(ServiceInstance, payload.instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="service instance not found")
    checks, agent, managed, observed, candidate = await run_deploy_prechecks(
        session,
        instance,
        settings,
        current_time,
        target_digest=payload.target_digest,
    )
    if not checks["passed"]:
        failed = [name for name, passed in checks.items() if name != "passed" and not passed]
        raise HTTPException(
            status_code=409, detail="deployment operation rejected: " + ", ".join(failed)
        )
    operation = Operation(
        instance_id=instance.id,
        agent_id=agent.id,
        action_type=DEPLOY_ACTION,
        status="planned",
        active_key=f"{instance.id}:write",
        requested_by="local-admin",
        risk_level="high",
        impact_summary="单个非关键 Compose 服务将以同仓库的不可变镜像摘要重建。",
        current_digest=candidate.current_digest,
        target_digest=payload.target_digest,
        plan_snapshot={
            "plan_version": DEPLOY_PLAN_VERSION,
            "execution_policy": DEPLOY_ACTION,
            "permanently_non_executable": False,
            "machine": {"id": agent.id, "name": agent.name, "hostname": agent.hostname},
            "service": {
                "id": managed.id,
                "name": managed.name,
                "environment": managed.environment,
                "instance_id": instance.id,
                "service_kind": instance.service_kind,
                "service_key": instance.service_key,
            },
            "repository": candidate.repository,
            "current_digest": candidate.current_digest,
            "target_digest": payload.target_digest,
            "candidate_observed_at": candidate.observed_at.isoformat(),
            "observed_state": observed.state if observed else None,
            "observed_healthy": observed.healthy if observed else None,
        },
        precheck_result=checks,
        verification_policy={
            "kind": "same_report_digest_and_health",
            "required_state": "running",
            "requires_healthy": True,
            "target_digest": payload.target_digest,
            "stability_seconds": settings.operation_verification_window_seconds,
            "timeout_seconds": settings.operation_verification_timeout_seconds,
        },
        idempotency_key="deploy_" + secrets.token_urlsafe(24),
        expires_at=current_time + timedelta(seconds=payload.expires_in_seconds),
    )
    try:
        async with session.begin_nested():
            session.add(operation)
            await session.flush()
            session.add(
                OperationTransition(
                    operation_id=operation.id,
                    from_status=None,
                    to_status="planned",
                    actor_type="admin",
                    actor_id="local-admin",
                    reason="controlled deployment requested",
                    details={"plan_version": DEPLOY_PLAN_VERSION},
                )
            )
            await transition(session, operation, "prechecking", "control_plane")
            await transition(session, operation, "awaiting_confirmation", "control_plane")
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="another write operation is active for this service"
        ) from error
    return await operation_view(session, operation)


@router.post(
    "/deployment-operations/{operation_id}/rollback",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_rollback_operation(
    operation_id: str,
    payload: OperationRollbackCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    source = await session.scalar(
        select(Operation).where(Operation.id == operation_id).with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="deployment operation not found")
    if not is_rollback_source(source):
        raise HTTPException(
            status_code=409,
            detail="rollback requires an executed, failed, original M4.2b deployment",
        )
    instance = await session.get(ServiceInstance, source.instance_id)
    if instance is None:
        raise HTTPException(status_code=409, detail="service instance no longer exists")
    current_time = now_utc()
    checks, agent, managed, observed, candidate = await run_rollback_prechecks(
        session, source, instance, settings, current_time
    )
    if not checks["passed"] or agent is None or managed is None or candidate is None:
        failed = [name for name, passed in checks.items() if name != "passed" and not passed]
        raise HTTPException(
            status_code=409, detail="rollback operation rejected: " + ", ".join(failed)
        )
    assert source.current_digest and source.target_digest
    operation = Operation(
        instance_id=instance.id,
        agent_id=agent.id,
        action_type=DEPLOY_ACTION,
        status="planned",
        active_key=f"{instance.id}:write",
        requested_by="local-admin",
        risk_level="high",
        impact_summary="显式回滚失败的 Compose 部署，恢复原计划冻结的旧镜像摘要。",
        current_digest=source.target_digest,
        target_digest=source.current_digest,
        rollback_of=source.id,
        plan_snapshot={
            "plan_version": ROLLBACK_PLAN_VERSION,
            "execution_policy": DEPLOY_ACTION,
            "permanently_non_executable": False,
            "rollback_of": source.id,
            "machine": {"id": agent.id, "name": agent.name, "hostname": agent.hostname},
            "service": {
                "id": managed.id,
                "name": managed.name,
                "environment": managed.environment,
                "instance_id": instance.id,
                "service_kind": instance.service_kind,
                "service_key": instance.service_key,
            },
            "repository": candidate.repository,
            "current_digest": source.target_digest,
            "target_digest": source.current_digest,
            "candidate_observed_at": candidate.observed_at.isoformat(),
            "observed_state": observed.state if observed else None,
            "observed_healthy": observed.healthy if observed else None,
        },
        precheck_result=checks,
        verification_policy={
            "kind": "same_report_digest_and_health",
            "required_state": "running",
            "requires_healthy": True,
            "target_digest": source.current_digest,
            "stability_seconds": settings.operation_verification_window_seconds,
            "timeout_seconds": settings.operation_verification_timeout_seconds,
        },
        idempotency_key="rollback_" + secrets.token_urlsafe(24),
        expires_at=current_time + timedelta(seconds=payload.expires_in_seconds),
    )
    try:
        async with session.begin_nested():
            session.add(operation)
            await session.flush()
            session.add(
                OperationTransition(
                    operation_id=operation.id,
                    from_status=None,
                    to_status="planned",
                    actor_type="admin",
                    actor_id="local-admin",
                    reason="explicit rollback requested",
                    details={"plan_version": ROLLBACK_PLAN_VERSION, "rollback_of": source.id},
                )
            )
            await transition(session, operation, "prechecking", "control_plane")
            await transition(session, operation, "awaiting_confirmation", "control_plane")
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="another write operation is active for this service"
        ) from error
    return await operation_view(session, operation)


@router.post(
    "/operations/{operation_id}/confirm",
    response_model=OperationView,
    dependencies=[Depends(require_admin)],
)
async def confirm_operation(
    operation_id: str,
    payload: OperationConfirm,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    operation = await session.scalar(
        select(Operation).where(Operation.id == operation_id).with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="operation not found")
    require_executable_action(operation)
    if operation.status == "queued":
        return await operation_view(session, operation)
    if operation.status != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="operation is not awaiting confirmation")
    current_time = now_utc()
    if operation.expires_at <= current_time:
        operation.error_code = "expired"
        operation.error_detail = "operation expired before confirmation"
        await transition(
            session, operation, "expired", "control_plane", reason=operation.error_detail
        )
        await session.commit()
        return await operation_view(session, operation)
    instance = await session.get(ServiceInstance, operation.instance_id)
    if instance is None:
        raise HTTPException(status_code=409, detail="service instance no longer exists")
    if operation.action_type == RESTART_ACTION:
        checks, _, _, _ = await run_prechecks(session, instance, settings, current_time)
    elif operation.rollback_of:
        source = await session.get(Operation, operation.rollback_of)
        checks, _, _, _, _ = await run_rollback_prechecks(
            session, source, instance, settings, current_time
        )
    else:
        if not operation.current_digest or not operation.target_digest:
            raise HTTPException(status_code=409, detail="deployment digest fields are incomplete")
        checks, _, _, _, _ = await run_deploy_prechecks(
            session,
            instance,
            settings,
            current_time,
            expected_current_digest=operation.current_digest,
            target_digest=operation.target_digest,
        )
    if not checks["passed"]:
        operation.error_code = "precheck_failed"
        operation.error_detail = "safety prechecks changed before confirmation"
        await transition(
            session,
            operation,
            "failed",
            "control_plane",
            reason=operation.error_detail,
            details={"confirmation_precheck": checks},
        )
        await session.commit()
        return await operation_view(session, operation)
    if not settings.operation_signing_key_id:
        raise HTTPException(status_code=503, detail="operation task signing is not configured")
    operation.confirmed_by = payload.confirmed_by
    operation.confirmed_at = current_time
    operation.issued_at = current_time
    operation.task_nonce = secrets.token_urlsafe(24)
    operation.signing_key_id = settings.operation_signing_key_id
    fields = (
        signing_fields(operation, instance)
        if operation.action_type == RESTART_ACTION
        else deployment_signing_fields(operation, instance)
    )
    operation.task_signature = sign_operation(
        settings.operation_signing_private_key_base64,
        fields,
    )
    await transition(
        session,
        operation,
        "queued",
        "admin",
        actor_id=payload.confirmed_by,
        reason="explicit confirmation",
        details={"plan_frozen": True, "confirmation_precheck": checks},
    )
    await session.commit()
    return await operation_view(session, operation)


@router.get("/operations/{operation_id}", response_model=OperationView)
async def get_operation(
    operation_id: str, session: AsyncSession = Depends(get_session)
) -> OperationView:
    operation = await session.get(Operation, operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="operation not found")
    return await operation_view(session, operation)


@router.post(
    "/operations/{operation_id}/cancel",
    response_model=OperationView,
    dependencies=[Depends(require_admin)],
)
async def cancel_operation(
    operation_id: str,
    session: AsyncSession = Depends(get_session),
) -> OperationView:
    operation = await session.scalar(
        select(Operation).where(Operation.id == operation_id).with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="operation not found")
    require_executable_action(operation)
    if operation.status == "canceled":
        return await operation_view(session, operation)
    if operation.status not in {"awaiting_confirmation", "queued"}:
        raise HTTPException(status_code=409, detail="operation can no longer be canceled safely")
    await transition(
        session,
        operation,
        "canceled",
        "admin",
        actor_id="local-admin",
        reason="canceled before Agent execution",
    )
    await session.commit()
    return await operation_view(session, operation)


@router.get("/agents/operations/next", response_model=OperationClaim)
async def claim_operation(
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationClaim:
    current_time = now_utc()
    operation = await session.scalar(
        select(Operation)
        .where(
            Operation.agent_id == agent.id,
            Operation.action_type.in_([RESTART_ACTION, DEPLOY_ACTION]),
            Operation.expires_at > current_time,
            or_(
                Operation.status == "queued",
                (Operation.status == "claimed") & (Operation.lease_expires_at <= current_time),
            ),
        )
        .order_by(Operation.requested_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if operation is None:
        return OperationClaim()
    instance = await session.get(ServiceInstance, operation.instance_id)
    if instance is None:
        operation.error_code = "invalid_task"
        operation.error_detail = "service instance is unavailable"
        await transition(
            session, operation, "failed", "control_plane", reason=operation.error_detail
        )
        await session.commit()
        return OperationClaim()
    try:
        require_executable_action(operation)
    except HTTPException:
        operation.error_code = "invalid_plan"
        operation.error_detail = "operation is not an executable signed plan version"
        await transition(
            session, operation, "failed", "control_plane", reason=operation.error_detail
        )
        await session.commit()
        return OperationClaim()
    if operation.task_signature is None:
        operation.error_code = "invalid_task"
        operation.error_detail = "signed task is incomplete"
        await transition(
            session, operation, "failed", "control_plane", reason=operation.error_detail
        )
        await session.commit()
        return OperationClaim()
    capability = await session.scalar(
        select(AgentOperationCapability).where(
            AgentOperationCapability.agent_id == agent.id,
            AgentOperationCapability.action_type == operation.action_type,
            AgentOperationCapability.service_kind == instance.service_kind,
            AgentOperationCapability.service_key == instance.service_key,
        )
    )
    if capability is None:
        operation.error_code = "capability_revoked"
        operation.error_detail = "Agent no longer declares the signed operation capability"
        await transition(
            session, operation, "failed", "control_plane", reason=operation.error_detail
        )
        await session.commit()
        return OperationClaim()
    reclaimed = operation.status == "claimed"
    operation.claimed_at = operation.claimed_at or current_time
    operation.lease_expires_at = current_time + timedelta(
        seconds=settings.operation_claim_lease_seconds
    )
    await transition(
        session,
        operation,
        "claimed",
        "agent",
        actor_id=agent.id,
        reason="claim lease renewed" if reclaimed else "task claimed",
        details={"lease_reclaimed": reclaimed},
    )
    await session.commit()
    common_task = {
        "operation_id": operation.id,
        "agent_id": agent.id,
        "service_kind": "docker",
        "service_key": instance.service_key,
        "issued_at": operation.issued_at,
        "expires_at": operation.expires_at,
        "idempotency_key": operation.idempotency_key,
        "attempt": operation.attempt,
        "nonce": operation.task_nonce,
        "key_id": operation.signing_key_id,
        "signature": operation.task_signature,
    }
    if operation.action_type == DEPLOY_ACTION:
        if not operation.current_digest or not operation.target_digest:
            operation.error_code = "invalid_task"
            operation.error_detail = "deployment digest fields are incomplete"
            await transition(
                session, operation, "failed", "control_plane", reason=operation.error_detail
            )
            await session.commit()
            return OperationClaim()
        return OperationClaim(
            task=DeploymentOperationTask(
                action_type=DEPLOY_ACTION,
                current_digest=operation.current_digest,
                target_digest=operation.target_digest,
                **common_task,
            )
        )
    return OperationClaim(
        task=OperationTask(
            action_type="docker_restart",
            **common_task,
        )
    )


@router.post("/agents/operations/{operation_id}/start", response_model=OperationReceipt)
async def start_operation(
    operation_id: str,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationReceipt:
    operation = await session.scalar(
        select(Operation).where(Operation.id == operation_id).with_for_update()
    )
    if operation is None or operation.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="operation not found")
    require_executable_action(operation)
    if operation.status == "running":
        return OperationReceipt(operation_id=operation.id, status=operation.status)
    if operation.status != "claimed" or operation.expires_at <= now_utc():
        raise HTTPException(status_code=409, detail="operation cannot be started")
    operation.started_at = now_utc()
    execution_timeout = (
        settings.operation_deploy_execution_timeout_seconds
        if operation.action_type == DEPLOY_ACTION
        else settings.operation_execution_timeout_seconds
    )
    operation.lease_expires_at = operation.started_at + timedelta(
        seconds=(execution_timeout + settings.operation_execution_result_grace_seconds)
    )
    await transition(session, operation, "running", "agent", actor_id=agent.id)
    await session.commit()
    return OperationReceipt(operation_id=operation.id, status=operation.status)


@router.post("/agents/operations/{operation_id}/complete", response_model=OperationReceipt)
async def complete_operation(
    operation_id: str,
    payload: OperationExecutionResult,
    agent: Agent = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationReceipt:
    operation = await session.scalar(
        select(Operation).where(Operation.id == operation_id).with_for_update()
    )
    if operation is None or operation.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="operation not found")
    require_executable_action(operation)
    if operation.status in {"verifying", "succeeded", "failed"}:
        return OperationReceipt(operation_id=operation.id, status=operation.status)
    rejected_before_start = operation.status == "claimed" and payload.status == "failed"
    if operation.status != "running" and not rejected_before_start:
        raise HTTPException(status_code=409, detail="operation is not running")
    output, redacted = redact_text(payload.output)
    output, lines_truncated = truncate_lines(output, settings.operation_max_output_lines)
    output, bytes_truncated = truncate_utf8(output, settings.operation_max_output_bytes)
    operation.output = output
    operation.output_truncated = payload.truncated or lines_truncated or bytes_truncated
    operation.exit_code = payload.exit_code
    operation.execution_completed_at = now_utc()
    operation.lease_expires_at = None
    if payload.status != "completed" or payload.exit_code != 0:
        operation.error_code = payload.error_code or "execution_failed"
        fallback = (
            "Docker Compose deployment execution failed"
            if operation.action_type == DEPLOY_ACTION
            else "Docker restart execution failed"
        )
        detail, _ = redact_text(payload.error_detail or fallback)
        operation.error_detail = detail[:512]
        await transition(
            session,
            operation,
            "failed",
            "agent",
            actor_id=agent.id,
            reason=operation.error_detail,
            details={"agent_redacted": redacted},
        )
    else:
        operation.verification_result = {"status": "waiting_for_fresh_observation"}
        await transition(
            session,
            operation,
            "verifying",
            "control_plane",
            reason="execution exited 0; awaiting independent health verification",
        )
    await session.commit()
    return OperationReceipt(operation_id=operation.id, status=operation.status)


async def reconcile_operation_verification(
    session: AsyncSession,
    agent: Agent,
    report: AgentReport,
    observed_at: datetime,
    settings: Settings,
) -> None:
    operations = list(
        (
            await session.scalars(
                select(Operation)
                .where(Operation.agent_id == agent.id, Operation.status == "verifying")
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    services = {(item.kind, item.key): item for item in report.services}
    candidates = {
        (item.service_kind, item.service_key): item for item in report.deployment_candidates
    }
    for operation in operations:
        instance = await session.get(ServiceInstance, operation.instance_id)
        service = services.get((instance.service_kind, instance.service_key)) if instance else None
        deadline = operation.execution_completed_at + timedelta(
            seconds=settings.operation_verification_timeout_seconds
        )
        if observed_at >= deadline:
            operation.verification_result = {
                "status": "failed",
                "reason": "healthy stability window was not reached before timeout",
                "observed_at": observed_at.isoformat(),
            }
            operation.error_code = "verification_timeout"
            operation.error_detail = "service did not become stably healthy before timeout"
            await transition(
                session, operation, "failed", "control_plane", reason=operation.error_detail
            )
            continue
        post_execution = bool(
            operation.execution_completed_at and observed_at > operation.execution_completed_at
        )
        candidate = (
            candidates.get((instance.service_kind, instance.service_key)) if instance else None
        )
        digest_matches = bool(
            operation.action_type != DEPLOY_ACTION
            or (
                candidate
                and candidate.eligible
                and candidate.current_digest == operation.target_digest
            )
        )
        healthy = bool(
            post_execution
            and service
            and service.healthy is True
            and service.state == "running"
            and digest_matches
        )
        previous = operation.verification_result or {}
        if not healthy:
            operation.verification_result = {
                "status": "waiting_for_deployment_observation"
                if operation.action_type == DEPLOY_ACTION
                else "waiting_for_healthy_observation",
                "observed_at": observed_at.isoformat(),
                "state": service.state if service else "missing",
                "healthy": service.healthy if service else None,
                "target_digest": operation.target_digest
                if operation.action_type == DEPLOY_ACTION
                else None,
                "observed_digest": candidate.current_digest
                if operation.action_type == DEPLOY_ACTION and candidate
                else None,
                "same_report": operation.action_type != DEPLOY_ACTION
                or (service is not None and candidate is not None),
            }
            continue
        first_value = previous.get("first_healthy_at")
        first_healthy = datetime.fromisoformat(first_value) if first_value else observed_at
        operation.verification_result = {
            "status": "stability_window",
            "first_healthy_at": first_healthy.isoformat(),
            "last_healthy_at": observed_at.isoformat(),
            "state": service.state,
            "healthy": service.healthy,
        }
        if operation.action_type == DEPLOY_ACTION:
            operation.verification_result["target_digest"] = operation.target_digest
            operation.verification_result["observed_digest"] = candidate.current_digest
        if observed_at >= first_healthy + timedelta(
            seconds=settings.operation_verification_window_seconds
        ):
            operation.verification_result["status"] = "passed"
            await transition(
                session,
                operation,
                "succeeded",
                "control_plane",
                reason=(
                    "same-report target digest and health satisfied the stability window"
                    if operation.action_type == DEPLOY_ACTION
                    else "fresh healthy observations satisfied the stability window"
                ),
            )


async def recover_stale_operations(
    settings: Settings, *, current_time: datetime | None = None
) -> int:
    observed_at = current_time or now_utc()
    changed = 0
    async with session_factory() as session:
        operations = list(
            (
                await session.scalars(
                    select(Operation)
                    .where(
                        Operation.status.in_(list(ACTIVE_STATUSES)),
                        or_(
                            and_(
                                Operation.status.in_(list(PRE_EXECUTION_STATUSES)),
                                Operation.expires_at <= observed_at,
                            ),
                            and_(
                                Operation.status == "running",
                                or_(
                                    Operation.lease_expires_at.is_(None),
                                    Operation.lease_expires_at <= observed_at,
                                ),
                            ),
                            and_(
                                Operation.status == "verifying",
                                or_(
                                    Operation.execution_completed_at.is_(None),
                                    Operation.execution_completed_at
                                    <= observed_at
                                    - timedelta(
                                        seconds=settings.operation_verification_timeout_seconds
                                    ),
                                ),
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for operation in operations:
            outcome = stale_operation_outcome(operation, settings, observed_at)
            if outcome is None:
                continue
            target, operation.error_code, operation.error_detail = outcome
            await transition(
                session, operation, target, "control_plane", reason=operation.error_detail
            )
            changed += 1
        await session.commit()
    return changed
