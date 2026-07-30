import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import require_admin
from .config import Settings, get_settings
from .conversation import ORGANIZATION_ID, scoped_event
from .database import get_session
from .models import (
    AlertEvent,
    ConversationSession,
    ConversationTurn,
    DiagnosticRun,
    ManagedService,
    Operation,
    OperationTransition,
    ServiceInstance,
)
from .operations import (
    DEPLOY_ACTION,
    DEPLOY_PLAN_VERSION,
    build_restart_plan,
    build_rollback_plan,
    is_rollback_source,
)
from .principal import observe_operation_plan
from .schemas import (
    ConversationAnswer,
    ConversationOperationCandidate,
    ConversationOperationCandidatesView,
    ConversationOperationTimelineItem,
    ConversationOperationTimelineTransition,
    ConversationOperationTimelineView,
    ConversationRestartPlanCreate,
    ConversationRollbackPlanCreate,
    OperationTransitionView,
    OperationView,
)

router = APIRouter(prefix="/api/v1")

RESTART_HANDOFF_KIND = "explicit_user_restart_plan"
ROLLBACK_HANDOFF_KIND = "explicit_user_rollback_plan"
RESTART_IMPACT_SUMMARY = "只创建非关键 Docker 服务的待确认重启计划"
ROLLBACK_IMPACT_SUMMARY = "只创建恢复失败 Compose 部署的待确认回滚计划"
MAX_CONVERSATION_OPERATIONS = 20
VERIFICATION_STATUSES = {
    "waiting_for_fresh_observation",
    "waiting_for_deployment_observation",
    "waiting_for_healthy_observation",
    "stability_window",
    "passed",
    "failed",
}
ERROR_SUMMARIES = {
    "precheck_failed": "前置检查未通过",
    "expired": "计划或任务已过期",
    "execution_failed": "Agent 报告执行失败",
    "execution_timeout": "Agent 执行超时",
    "execution_outcome_unknown": "执行结果无法确认",
    "verification_timeout": "健康验证超时",
    "invalid_task": "任务未通过控制平面校验",
}


def _sha256_json(value: dict) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _operation_view(
    session: AsyncSession,
    operation: Operation,
) -> OperationView:
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


async def _event_instance(
    session: AsyncSession,
    event_id: str,
    *,
    organization_id: str,
) -> tuple[ServiceInstance | None, ManagedService | None]:
    event = await scoped_event(session, event_id, organization_id)
    if event.source != "service" or not event.service_kind or not event.service_key:
        return None, None
    row = await session.execute(
        select(ServiceInstance, ManagedService)
        .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
        .where(
            ServiceInstance.agent_id == event.agent_id,
            ServiceInstance.service_kind == event.service_kind,
            ServiceInstance.service_key == event.service_key,
            ManagedService.organization_id == organization_id,
        )
    )
    result = row.first()
    return result if result is not None else (None, None)


def _candidate(
    *,
    action_type: str,
    available: bool,
    reason_code: str | None,
    impact_summary: str,
) -> ConversationOperationCandidate:
    return ConversationOperationCandidate(
        action_type=action_type,
        available=available,
        reason_code=reason_code,
        impact_summary=impact_summary,
    )


async def _rollback_source_for_event(
    session: AsyncSession,
    event: AlertEvent,
    instance: ServiceInstance,
    *,
    lock: bool = False,
) -> tuple[Operation | None, str | None]:
    """Resolve one failed deployment whose execution overlaps this event."""

    statement = (
        select(Operation)
        .where(
            Operation.organization_id == event.organization_id,
            Operation.instance_id == instance.id,
            or_(
                Operation.source_event_id.is_(None),
                Operation.source_event_id == event.id,
            ),
            Operation.action_type == DEPLOY_ACTION,
            Operation.status == "failed",
            Operation.rollback_of.is_(None),
            Operation.started_at.is_not(None),
            Operation.completed_at.is_not(None),
            Operation.current_digest.is_not(None),
            Operation.target_digest.is_not(None),
            Operation.plan_snapshot["plan_version"].as_string() == DEPLOY_PLAN_VERSION,
            Operation.started_at <= event.last_observed_at,
            Operation.completed_at >= event.first_observed_at,
        )
        .order_by(Operation.started_at.desc(), Operation.id)
        .limit(2)
    )
    if lock:
        statement = statement.with_for_update()
    candidates = [
        item
        for item in (await session.scalars(statement)).all()
        if is_rollback_source(item)
    ]
    if not candidates:
        return None, "rollback_source_not_found"
    if len(candidates) != 1:
        return None, "rollback_source_ambiguous"
    return candidates[0], None


@router.get(
    "/events/{event_id}/conversation/operation-candidates",
    response_model=ConversationOperationCandidatesView,
)
async def conversation_operation_candidates(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConversationOperationCandidatesView:
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    if not settings.conversation_operation_handoff_enabled:
        restart = _candidate(
            action_type="docker_restart",
            available=False,
            reason_code="feature_disabled",
            impact_summary=RESTART_IMPACT_SUMMARY,
        )
        rollback = _candidate(
            action_type="docker_compose_rollback",
            available=False,
            reason_code="feature_disabled",
            impact_summary=ROLLBACK_IMPACT_SUMMARY,
        )
    elif event.source != "service" or not event.service_kind or not event.service_key:
        restart = _candidate(
            action_type="docker_restart",
            available=False,
            reason_code="event_not_service",
            impact_summary=RESTART_IMPACT_SUMMARY,
        )
        rollback = _candidate(
            action_type="docker_compose_rollback",
            available=False,
            reason_code="event_not_service",
            impact_summary=ROLLBACK_IMPACT_SUMMARY,
        )
    else:
        instance, managed = await _event_instance(
            session,
            event.id,
            organization_id=event.organization_id,
        )
        if instance is None or managed is None:
            restart_reason = rollback_reason = "service_not_mapped"
        elif instance.service_kind != "docker":
            restart_reason = rollback_reason = "not_docker"
        elif managed.criticality != "non_critical":
            restart_reason = rollback_reason = "critical_service"
        else:
            restart_reason = None if instance.restart_enabled else "restart_disabled"
            if not instance.deploy_enabled:
                rollback_reason = "deploy_disabled"
            else:
                _, rollback_reason = await _rollback_source_for_event(
                    session,
                    event,
                    instance,
                )
        restart = _candidate(
            action_type="docker_restart",
            available=restart_reason is None,
            reason_code=restart_reason,
            impact_summary=RESTART_IMPACT_SUMMARY,
        )
        rollback = _candidate(
            action_type="docker_compose_rollback",
            available=rollback_reason is None,
            reason_code=rollback_reason,
            impact_summary=ROLLBACK_IMPACT_SUMMARY,
        )
    return ConversationOperationCandidatesView(
        event_id=event.id,
        candidates=[restart, rollback],
    )


def _timeline_source_turn_id(operation: Operation) -> str | None:
    if operation.source_conversation_turn_id:
        return operation.source_conversation_turn_id
    conversation_source = operation.plan_snapshot.get("conversation_source")
    if not isinstance(conversation_source, dict):
        return None
    turn_id = conversation_source.get("turn_id")
    return turn_id if isinstance(turn_id, str) and len(turn_id) <= 36 else None


def _timeline_verification_status(operation: Operation) -> str | None:
    if not isinstance(operation.verification_result, dict):
        return None
    verification_status = operation.verification_result.get("status")
    return (
        verification_status
        if isinstance(verification_status, str)
        and verification_status in VERIFICATION_STATUSES
        else None
    )


def _timeline_error_summary(operation: Operation) -> str | None:
    if not operation.error_code:
        return None
    return ERROR_SUMMARIES.get(
        operation.error_code,
        "操作未成功；请在操作详情页查看受控错误信息",
    )


@router.get(
    "/events/{event_id}/conversation/operations",
    response_model=ConversationOperationTimelineView,
)
async def conversation_operation_timeline(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConversationOperationTimelineView:
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    if not settings.conversation_operation_timeline_enabled:
        return ConversationOperationTimelineView(
            event_id=event.id,
            available=False,
            unavailable_reason="feature_disabled",
            operations=[],
        )

    diagnostic_ids = select(DiagnosticRun.id).where(
        DiagnosticRun.organization_id == event.organization_id,
        DiagnosticRun.event_id == event.id,
    )
    conversation_turn_ids = (
        select(ConversationTurn.id)
        .join(
            ConversationSession,
            ConversationSession.id == ConversationTurn.session_id,
        )
        .where(
            ConversationTurn.organization_id == event.organization_id,
            ConversationSession.organization_id == event.organization_id,
            ConversationSession.scope_type == "event",
            ConversationSession.event_id == event.id,
        )
    )
    operations = list(
        (
            await session.scalars(
                select(Operation)
                .where(
                    Operation.organization_id == event.organization_id,
                    or_(
                        Operation.source_event_id == event.id,
                        Operation.source_diagnostic_id.in_(diagnostic_ids),
                        Operation.source_conversation_turn_id.in_(
                            conversation_turn_ids
                        ),
                    ),
                )
                .order_by(Operation.requested_at.desc(), Operation.id)
                .limit(MAX_CONVERSATION_OPERATIONS)
            )
        ).all()
    )
    transitions_by_operation: dict[
        str, list[ConversationOperationTimelineTransition]
    ] = {operation.id: [] for operation in operations}
    if operations:
        transitions = list(
            (
                await session.scalars(
                    select(OperationTransition)
                    .where(
                        OperationTransition.operation_id.in_(
                            [operation.id for operation in operations]
                        )
                    )
                    .order_by(
                        OperationTransition.created_at,
                        OperationTransition.id,
                    )
                )
            ).all()
        )
        for transition in transitions:
            transitions_by_operation.setdefault(transition.operation_id, []).append(
                ConversationOperationTimelineTransition(
                    from_status=transition.from_status,
                    to_status=transition.to_status,
                    actor_type=transition.actor_type,
                    created_at=transition.created_at,
                )
            )

    return ConversationOperationTimelineView(
        event_id=event.id,
        available=True,
        unavailable_reason=None,
        operations=[
            ConversationOperationTimelineItem(
                id=operation.id,
                source_conversation_turn_id=_timeline_source_turn_id(operation),
                action_type=operation.action_type,
                status=operation.status,
                impact_summary=operation.impact_summary,
                verification_status=_timeline_verification_status(operation),
                error_code=operation.error_code,
                error_summary=_timeline_error_summary(operation),
                requested_at=operation.requested_at,
                completed_at=operation.completed_at,
                transitions=transitions_by_operation.get(operation.id, []),
            )
            for operation in operations
        ],
    )


async def _scoped_completed_turn(
    session: AsyncSession,
    event_id: str,
    turn_id: str,
    *,
    organization_id: str,
) -> tuple[ConversationTurn, ConversationAnswer]:
    conversation = await session.scalar(
        select(ConversationSession).where(
            ConversationSession.event_id == event_id,
            ConversationSession.organization_id == organization_id,
            ConversationSession.scope_type == "event",
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation turn not found")
    turn = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.id == turn_id,
            ConversationTurn.session_id == conversation.id,
            ConversationTurn.organization_id == organization_id,
        )
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="conversation turn not found")
    if turn.status != "completed" or turn.answer is None:
        raise HTTPException(
            status_code=409,
            detail="conversation turn is not eligible for operation handoff",
        )
    try:
        answer = ConversationAnswer.model_validate(turn.answer)
    except ValidationError as error:
        raise HTTPException(
            status_code=409,
            detail="conversation turn is not eligible for operation handoff",
        ) from error
    return turn, answer


def _same_handoff(
    operation: Operation,
    *,
    event_id: str,
    turn_id: str,
    action_type: str,
    handoff_kind: str,
) -> bool:
    conversation_source = operation.plan_snapshot.get("conversation_source", {})
    return (
        operation.source_event_id == event_id
        and operation.source_conversation_turn_id == turn_id
        and operation.action_type == action_type
        and conversation_source.get("handoff_kind") == handoff_kind
    )


@router.post(
    "/events/{event_id}/conversation/turns/{turn_id}/restart-plan",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(observe_operation_plan), Depends(require_admin)],
)
async def create_conversation_restart_plan(
    event_id: str,
    turn_id: str,
    payload: ConversationRestartPlanCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    if not settings.conversation_operation_handoff_enabled:
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_handoff_disabled",
        )
    turn, answer = await _scoped_completed_turn(
        session,
        event.id,
        turn_id,
        organization_id=event.organization_id,
    )
    scoped_organization_id = event.organization_id
    scoped_event_id = event.id
    scoped_turn_id = turn.id
    request_id = str(payload.client_request_id)
    existing = await session.scalar(
        select(Operation).where(
            Operation.organization_id == event.organization_id,
            Operation.conversation_request_id == request_id,
        )
    )
    if existing is not None:
        if not _same_handoff(
            existing,
            event_id=event.id,
            turn_id=turn.id,
            action_type="docker_restart",
            handoff_kind=RESTART_HANDOFF_KIND,
        ):
            raise HTTPException(
                status_code=409,
                detail="conversation request id is already in use",
            )
        return await _operation_view(session, existing)
    instance, managed = await _event_instance(
        session,
        event.id,
        organization_id=event.organization_id,
    )
    if instance is None or managed is None:
        raise HTTPException(status_code=409, detail="event service is not mapped")
    source = {
        "organization_id": event.organization_id,
        "turn_id": turn.id,
        "conversation_request_id": request_id,
        "conversation_source": {
            "turn_id": turn.id,
            "answer_sha256": _sha256_json(answer.model_dump(mode="json")),
            "context_manifest_sha256": _sha256_json(turn.context_manifest),
            "handoff_kind": RESTART_HANDOFF_KIND,
        },
        "reason": "conversation restart plan explicitly requested",
        "transition_details": {
            "source": "conversation_handoff",
            "turn_id": turn.id,
        },
    }
    try:
        operation = await build_restart_plan(
            session,
            instance,
            event,
            None,
            settings,
            expires_in_seconds=payload.expires_in_seconds,
            source_metadata=source,
        )
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(Operation).where(
                Operation.organization_id == scoped_organization_id,
                Operation.conversation_request_id == request_id,
            )
        )
        if existing is not None:
            if not _same_handoff(
                existing,
                event_id=scoped_event_id,
                turn_id=scoped_turn_id,
                action_type="docker_restart",
                handoff_kind=RESTART_HANDOFF_KIND,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="conversation request id is already in use",
                ) from error
            return await _operation_view(session, existing)
        raise HTTPException(
            status_code=409,
            detail="another write operation is active for this service",
        ) from error
    if operation.status not in {"awaiting_confirmation", "failed"}:
        raise RuntimeError("restart plan exceeded the M5.3 state ceiling")
    return await _operation_view(session, operation)


@router.post(
    "/events/{event_id}/conversation/turns/{turn_id}/rollback-plan",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(observe_operation_plan), Depends(require_admin)],
)
async def create_conversation_rollback_plan(
    event_id: str,
    turn_id: str,
    payload: ConversationRollbackPlanCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationView:
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    if not settings.conversation_operation_handoff_enabled:
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_handoff_disabled",
        )
    turn, answer = await _scoped_completed_turn(
        session,
        event.id,
        turn_id,
        organization_id=event.organization_id,
    )
    scoped_organization_id = event.organization_id
    scoped_event_id = event.id
    scoped_turn_id = turn.id
    request_id = str(payload.client_request_id)
    existing = await session.scalar(
        select(Operation).where(
            Operation.organization_id == event.organization_id,
            Operation.conversation_request_id == request_id,
        )
    )
    if existing is not None:
        if not _same_handoff(
            existing,
            event_id=event.id,
            turn_id=turn.id,
            action_type=DEPLOY_ACTION,
            handoff_kind=ROLLBACK_HANDOFF_KIND,
        ):
            raise HTTPException(
                status_code=409,
                detail="conversation request id is already in use",
            )
        return await _operation_view(session, existing)
    instance, managed = await _event_instance(
        session,
        event.id,
        organization_id=event.organization_id,
    )
    if instance is None or managed is None:
        raise HTTPException(status_code=409, detail="event service is not mapped")
    source_operation, source_error = await _rollback_source_for_event(
        session,
        event,
        instance,
        lock=True,
    )
    if source_operation is None:
        raise HTTPException(
            status_code=409,
            detail=source_error or "rollback_source_not_found",
        )
    source = {
        "organization_id": event.organization_id,
        "event_id": event.id,
        "turn_id": turn.id,
        "conversation_request_id": request_id,
        "conversation_source": {
            "turn_id": turn.id,
            "answer_sha256": _sha256_json(answer.model_dump(mode="json")),
            "context_manifest_sha256": _sha256_json(turn.context_manifest),
            "handoff_kind": ROLLBACK_HANDOFF_KIND,
        },
        "reason": "conversation rollback plan explicitly requested",
        "transition_details": {
            "source": "conversation_handoff",
            "turn_id": turn.id,
        },
    }
    try:
        operation = await build_rollback_plan(
            session,
            source_operation,
            settings,
            expires_in_seconds=payload.expires_in_seconds,
            source_metadata=source,
        )
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(Operation).where(
                Operation.organization_id == scoped_organization_id,
                Operation.conversation_request_id == request_id,
            )
        )
        if existing is not None:
            if not _same_handoff(
                existing,
                event_id=scoped_event_id,
                turn_id=scoped_turn_id,
                action_type=DEPLOY_ACTION,
                handoff_kind=ROLLBACK_HANDOFF_KIND,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="conversation request id is already in use",
                ) from error
            return await _operation_view(session, existing)
        raise HTTPException(
            status_code=409,
            detail="another write operation is active for this service",
        ) from error
    if operation.status != "awaiting_confirmation":
        raise RuntimeError("rollback plan exceeded the M5.3 state ceiling")
    return await _operation_view(session, operation)
