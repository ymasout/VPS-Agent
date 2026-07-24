import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import require_admin
from .config import Settings, get_settings
from .conversation import ORGANIZATION_ID, scoped_event
from .database import get_session
from .models import (
    ConversationSession,
    ConversationTurn,
    ManagedService,
    Operation,
    OperationTransition,
    ServiceInstance,
)
from .operations import build_restart_plan
from .schemas import (
    ConversationAnswer,
    ConversationOperationCandidate,
    ConversationOperationCandidatesView,
    ConversationRestartPlanCreate,
    OperationTransitionView,
    OperationView,
)

router = APIRouter(prefix="/api/v1")

HANDOFF_KIND = "explicit_user_restart_plan"
IMPACT_SUMMARY = "只创建非关键 Docker 服务的待确认重启计划"


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
    available: bool,
    reason_code: str | None,
) -> ConversationOperationCandidate:
    return ConversationOperationCandidate(
        available=available,
        reason_code=reason_code,
        impact_summary=IMPACT_SUMMARY,
    )


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
        candidate = _candidate(available=False, reason_code="feature_disabled")
    elif event.source != "service" or not event.service_kind or not event.service_key:
        candidate = _candidate(available=False, reason_code="event_not_service")
    else:
        instance, managed = await _event_instance(
            session,
            event.id,
            organization_id=event.organization_id,
        )
        if instance is None or managed is None:
            candidate = _candidate(available=False, reason_code="service_not_mapped")
        elif instance.service_kind != "docker":
            candidate = _candidate(available=False, reason_code="not_docker")
        elif managed.criticality != "non_critical":
            candidate = _candidate(available=False, reason_code="critical_service")
        elif not instance.restart_enabled:
            candidate = _candidate(available=False, reason_code="restart_disabled")
        else:
            candidate = _candidate(available=True, reason_code=None)
    return ConversationOperationCandidatesView(
        event_id=event.id,
        candidates=[candidate],
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
) -> bool:
    return (
        operation.source_event_id == event_id
        and operation.source_conversation_turn_id == turn_id
        and operation.action_type == "docker_restart"
    )


@router.post(
    "/events/{event_id}/conversation/turns/{turn_id}/restart-plan",
    response_model=OperationView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
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
    request_id = str(payload.client_request_id)
    existing = await session.scalar(
        select(Operation).where(
            Operation.organization_id == event.organization_id,
            Operation.conversation_request_id == request_id,
        )
    )
    if existing is not None:
        if not _same_handoff(existing, event_id=event.id, turn_id=turn.id):
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
            "handoff_kind": HANDOFF_KIND,
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
                Operation.organization_id == event.organization_id,
                Operation.conversation_request_id == request_id,
            )
        )
        if existing is not None:
            if not _same_handoff(existing, event_id=event.id, turn_id=turn.id):
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
