import base64
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import require_admin
from .config import Settings, get_settings
from .conversation import (
    MAX_TURNS_RETURNED,
    ORGANIZATION_ID,
    ContextItem,
    ConversationContext,
    ConversationFailure,
    citation_href,
    fit_context_items,
    json_text,
    make_context_item,
    run_conversation_turn,
    scoped_event,
    turn_view,
)
from .database import get_session
from .models import (
    Agent,
    AlertEvent,
    ConversationCitation,
    ConversationSession,
    ConversationTurn,
    ConversationTurnFeedback,
    DiagnosticRun,
    EvidenceItem,
    FleetConversationSnapshot,
    ManagedService,
    Operation,
    RunbookDraft,
    ServiceInstance,
    ServiceStatus,
)
from .redaction import redact_text, truncate_utf8
from .schemas import (
    ConversationAnswer,
    ConversationFeedbackUpdate,
    ConversationFeedbackView,
    ConversationQuestion,
    ConversationTurnView,
    EventHistoryItemView,
    EventHistoryView,
    EventReviewSourceView,
    EventReviewView,
    FleetConversationView,
    RunbookDraftCitationView,
    RunbookDraftCreate,
    RunbookDraftView,
    SimilarEventsView,
    SimilarEventView,
)

router = APIRouter(prefix="/api/v1")

FLEET_SNAPSHOT_VERSION = "m5.5-fleet-snapshot-v1"
SIMILARITY_VERSION = "m5.6-similarity-v1"
MAX_FLEET_AGENTS = 12
MAX_FLEET_INSTANCES = 20
MAX_FLEET_EVENTS = 20
MAX_FLEET_OPERATIONS = 10
MAX_FLEET_DIAGNOSTICS = 10
MAX_FLEET_EVIDENCE = 12
MAX_FLEET_HISTORY = 6


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_fleet_content(
    captured_at: datetime,
    counts: dict[str, int],
    omitted_counts: dict[str, int],
) -> str:
    return json_text(
        {
            "schema_version": FLEET_SNAPSHOT_VERSION,
            "captured_at": captured_at.isoformat(),
            "counts": counts,
            "omitted_counts": omitted_counts,
        }
    )


def _fleet_snapshot_sha256(
    captured_at: datetime,
    counts: dict[str, int],
    selected_source_ids: dict[str, list[str]],
    omitted_counts: dict[str, int],
) -> str:
    canonical = json_text(
        {
            "schema_version": FLEET_SNAPSHOT_VERSION,
            "captured_at": captured_at.isoformat(),
            "counts": counts,
            "selected_source_ids": selected_source_ids,
            "omitted_counts": omitted_counts,
        }
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_count_map(values: dict[str, int]) -> None:
    if any(
        not isinstance(key, str)
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for key, value in values.items()
    ):
        raise ConversationFailure(
            "context_assembly_failed", "Fleet snapshot contains invalid counts"
        )


async def _set_repeatable_read(session: AsyncSession) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))


async def capture_fleet_snapshot(
    session: AsyncSession,
    turn: ConversationTurn,
    settings: Settings,
) -> FleetConversationSnapshot:
    now = utcnow()
    offline_before = now - timedelta(seconds=settings.agent_offline_after_seconds)
    organization_id = turn.organization_id

    agent_total = int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(
                Agent.organization_id == organization_id
            )
        )
        or 0
    )
    agent_offline = int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(
                Agent.organization_id == organization_id,
                or_(Agent.last_seen_at.is_(None), Agent.last_seen_at < offline_before),
            )
        )
        or 0
    )
    instance_total = int(
        await session.scalar(
            select(func.count())
            .select_from(ServiceInstance)
            .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
            .join(Agent, Agent.id == ServiceInstance.agent_id)
            .where(
                ManagedService.organization_id == organization_id,
                Agent.organization_id == organization_id,
            )
        )
        or 0
    )
    unhealthy_total = int(
        await session.scalar(
            select(func.count())
            .select_from(ServiceInstance)
            .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
            .join(Agent, Agent.id == ServiceInstance.agent_id)
            .join(
                ServiceStatus,
                (ServiceStatus.agent_id == ServiceInstance.agent_id)
                & (ServiceStatus.kind == ServiceInstance.service_kind)
                & (ServiceStatus.service_key == ServiceInstance.service_key),
            )
            .where(
                ManagedService.organization_id == organization_id,
                Agent.organization_id == organization_id,
                or_(
                    ServiceStatus.healthy.is_(False),
                    ServiceStatus.state.notin_(["running", "active"]),
                ),
            )
        )
        or 0
    )
    active_event_total = int(
        await session.scalar(
            select(func.count()).select_from(AlertEvent).where(
                AlertEvent.organization_id == organization_id,
                AlertEvent.status != "resolved",
            )
        )
        or 0
    )
    critical_event_total = int(
        await session.scalar(
            select(func.count()).select_from(AlertEvent).where(
                AlertEvent.organization_id == organization_id,
                AlertEvent.status != "resolved",
                AlertEvent.severity == "critical",
            )
        )
        or 0
    )
    operation_active_total = int(
        await session.scalar(
            select(func.count()).select_from(Operation).where(
                Operation.organization_id == organization_id,
                Operation.status.in_(
                    [
                        "awaiting_confirmation",
                        "queued",
                        "claimed",
                        "running",
                        "verifying",
                    ]
                ),
            )
        )
        or 0
    )
    operation_failed_total = int(
        await session.scalar(
            select(func.count()).select_from(Operation).where(
                Operation.organization_id == organization_id,
                Operation.status.in_(["failed", "verification_failed"]),
            )
        )
        or 0
    )

    agent_ids = list(
        (
            await session.scalars(
                select(Agent.id)
                .where(Agent.organization_id == organization_id)
                .order_by(
                    case(
                        (
                            or_(
                                Agent.last_seen_at.is_(None),
                                Agent.last_seen_at < offline_before,
                            ),
                            0,
                        ),
                        else_=1,
                    ),
                    Agent.last_seen_at.asc().nullsfirst(),
                    Agent.id,
                )
                .limit(MAX_FLEET_AGENTS)
            )
        ).all()
    )
    instance_ids = list(
        (
            await session.scalars(
                select(ServiceInstance.id)
                .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
                .join(Agent, Agent.id == ServiceInstance.agent_id)
                .outerjoin(
                    ServiceStatus,
                    (ServiceStatus.agent_id == ServiceInstance.agent_id)
                    & (ServiceStatus.kind == ServiceInstance.service_kind)
                    & (ServiceStatus.service_key == ServiceInstance.service_key),
                )
                .where(
                    ManagedService.organization_id == organization_id,
                    Agent.organization_id == organization_id,
                )
                .order_by(
                    case(
                        (
                            or_(
                                ServiceStatus.id.is_(None),
                                ServiceStatus.healthy.is_(False),
                                ServiceStatus.state.notin_(["running", "active"]),
                            ),
                            0,
                        ),
                        else_=1,
                    ),
                    ServiceStatus.observed_at.asc().nullsfirst(),
                    ServiceInstance.id,
                )
                .limit(MAX_FLEET_INSTANCES)
            )
        ).all()
    )
    event_ids = list(
        (
            await session.scalars(
                select(AlertEvent.id)
                .where(
                    AlertEvent.organization_id == organization_id,
                    AlertEvent.status != "resolved",
                )
                .order_by(
                    case((AlertEvent.severity == "critical", 0), else_=1),
                    AlertEvent.last_observed_at.desc(),
                    AlertEvent.id,
                )
                .limit(MAX_FLEET_EVENTS)
            )
        ).all()
    )
    operation_ids = list(
        (
            await session.scalars(
                select(Operation.id)
                .where(
                    Operation.organization_id == organization_id,
                    Operation.status.in_(
                        [
                            "failed",
                            "verification_failed",
                            "verifying",
                            "awaiting_confirmation",
                            "queued",
                            "claimed",
                            "running",
                        ]
                    ),
                )
                .order_by(Operation.requested_at.desc(), Operation.id)
                .limit(MAX_FLEET_OPERATIONS)
            )
        ).all()
    )
    diagnostic_ids = (
        list(
            (
                await session.scalars(
                    select(DiagnosticRun.id)
                    .where(
                        DiagnosticRun.organization_id == organization_id,
                        DiagnosticRun.event_id.in_(event_ids),
                        DiagnosticRun.status == "completed",
                    )
                    .order_by(DiagnosticRun.completed_at.desc(), DiagnosticRun.id)
                    .limit(MAX_FLEET_DIAGNOSTICS)
                )
            ).all()
        )
        if event_ids
        else []
    )
    diagnostic_total = (
        int(
            await session.scalar(
                select(func.count()).select_from(DiagnosticRun).where(
                    DiagnosticRun.organization_id == organization_id,
                    DiagnosticRun.event_id.in_(event_ids),
                    DiagnosticRun.status == "completed",
                )
            )
            or 0
        )
        if event_ids
        else 0
    )
    evidence_ids = (
        list(
            (
                await session.scalars(
                    select(EvidenceItem.id)
                    .join(DiagnosticRun, DiagnosticRun.id == EvidenceItem.diagnostic_id)
                    .where(
                        DiagnosticRun.organization_id == organization_id,
                        EvidenceItem.diagnostic_id.in_(diagnostic_ids),
                    )
                    .order_by(EvidenceItem.collected_at.desc(), EvidenceItem.id)
                    .limit(MAX_FLEET_EVIDENCE)
                )
            ).all()
        )
        if diagnostic_ids
        else []
    )
    evidence_total = (
        int(
            await session.scalar(
                select(func.count())
                .select_from(EvidenceItem)
                .join(DiagnosticRun, DiagnosticRun.id == EvidenceItem.diagnostic_id)
                .where(
                    DiagnosticRun.organization_id == organization_id,
                    EvidenceItem.diagnostic_id.in_(diagnostic_ids),
                )
            )
            or 0
        )
        if diagnostic_ids
        else 0
    )

    counts = {
        "agents_total": agent_total,
        "agents_online": max(agent_total - agent_offline, 0),
        "agents_offline": agent_offline,
        "service_instances_total": instance_total,
        "service_instances_unhealthy": unhealthy_total,
        "active_events_total": active_event_total,
        "active_events_critical": critical_event_total,
        "active_operations_total": operation_active_total,
        "failed_operations_total": operation_failed_total,
    }
    selected_source_ids = {
        "agent_summary": agent_ids,
        "service_instance_summary": instance_ids,
        "alert_event": event_ids,
        "operation": operation_ids,
        "diagnostic_run": diagnostic_ids,
        "evidence_item": evidence_ids,
    }
    omitted_counts = {
        "agent_summary": max(agent_total - len(agent_ids), 0),
        "service_instance_summary": max(instance_total - len(instance_ids), 0),
        "alert_event": max(active_event_total - len(event_ids), 0),
        "operation": max(
            operation_active_total + operation_failed_total - len(operation_ids), 0
        ),
        "diagnostic_run": max(diagnostic_total - len(diagnostic_ids), 0),
        "evidence_item": max(evidence_total - len(evidence_ids), 0),
    }
    _validate_count_map(counts)
    _validate_count_map(omitted_counts)
    snapshot = FleetConversationSnapshot(
        organization_id=organization_id,
        turn_id=turn.id,
        schema_version=FLEET_SNAPSHOT_VERSION,
        captured_at=now,
        counts=counts,
        selected_source_ids=selected_source_ids,
        omitted_counts=omitted_counts,
        content_sha256=_fleet_snapshot_sha256(
            now, counts, selected_source_ids, omitted_counts
        ),
    )
    session.add(snapshot)
    await session.flush()
    turn.context_manifest = {
        "version": "m5.5-fleet-conversation-v1",
        "scope_type": "fleet",
        "fleet_snapshot_id": snapshot.id,
        "captured_at": now.isoformat(),
        "counts": counts,
        "omitted_counts": omitted_counts,
    }
    return snapshot


def _ordered_rows(rows: list[object], ids: list[str]) -> list[object]:
    positions = {value: index for index, value in enumerate(ids)}
    return sorted(rows, key=lambda row: positions[getattr(row, "id")])


async def build_fleet_context(
    session: AsyncSession,
    turn: ConversationTurn,
    settings: Settings,
) -> ConversationContext:
    snapshot = await session.scalar(
        select(FleetConversationSnapshot).where(
            FleetConversationSnapshot.turn_id == turn.id,
            FleetConversationSnapshot.organization_id == turn.organization_id,
        )
    )
    if snapshot is None or snapshot.schema_version != FLEET_SNAPSHOT_VERSION:
        raise ConversationFailure(
            "context_assembly_failed", "Fleet snapshot is missing or unsupported"
        )
    _validate_count_map(snapshot.counts)
    _validate_count_map(snapshot.omitted_counts)
    if (
        _fleet_snapshot_sha256(
            snapshot.captured_at,
            snapshot.counts,
            snapshot.selected_source_ids,
            snapshot.omitted_counts,
        )
        != snapshot.content_sha256
    ):
        raise ConversationFailure(
            "context_assembly_failed", "Fleet snapshot digest is invalid"
        )

    candidates: list[ContextItem] = [
        make_context_item(
            turn.id,
            "fleet_snapshot",
            snapshot.id,
            "Fleet 时间点汇总",
            _canonical_fleet_content(
                snapshot.captured_at, snapshot.counts, snapshot.omitted_counts
            ),
            snapshot.captured_at,
            8192,
        )
    ]
    selected = snapshot.selected_source_ids

    agent_ids = list(selected.get("agent_summary", []))
    agents = (
        list(
            (
                await session.scalars(
                    select(Agent).where(
                        Agent.organization_id == turn.organization_id,
                        Agent.id.in_(agent_ids),
                    )
                )
            ).all()
        )
        if agent_ids
        else []
    )
    for agent in _ordered_rows(agents, agent_ids):
        candidates.append(
            make_context_item(
                turn.id,
                "agent_summary",
                agent.id,
                f"Agent {agent.name}",
                json_text(
                    {
                        "name": agent.name,
                        "hostname": agent.hostname,
                        "version": agent.version,
                        "last_seen_at": agent.last_seen_at,
                    }
                ),
                agent.last_seen_at or snapshot.captured_at,
                4096,
            )
        )

    instance_ids = list(selected.get("service_instance_summary", []))
    instance_rows = (
        list(
            (
                await session.execute(
                    select(ServiceInstance, ManagedService, ServiceStatus)
                    .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
                    .join(Agent, Agent.id == ServiceInstance.agent_id)
                    .outerjoin(
                        ServiceStatus,
                        (ServiceStatus.agent_id == ServiceInstance.agent_id)
                        & (ServiceStatus.kind == ServiceInstance.service_kind)
                        & (ServiceStatus.service_key == ServiceInstance.service_key),
                    )
                    .where(
                        ManagedService.organization_id == turn.organization_id,
                        Agent.organization_id == turn.organization_id,
                        ServiceInstance.id.in_(instance_ids),
                    )
                )
            ).all()
        )
        if instance_ids
        else []
    )
    position = {value: index for index, value in enumerate(instance_ids)}
    for instance, service, observed in sorted(
        instance_rows, key=lambda row: position[row[0].id]
    ):
        candidates.append(
            make_context_item(
                turn.id,
                "service_instance_summary",
                instance.id,
                f"服务 {service.name}",
                json_text(
                    {
                        "service": service.name,
                        "environment": service.environment,
                        "criticality": service.criticality,
                        "kind": instance.service_kind,
                        "state": observed.state if observed else "unknown",
                        "healthy": observed.healthy if observed else None,
                        "observed_at": observed.observed_at if observed else None,
                    }
                ),
                observed.observed_at if observed else snapshot.captured_at,
                4096,
            )
        )

    event_ids = list(selected.get("alert_event", []))
    events = (
        list(
            (
                await session.scalars(
                    select(AlertEvent).where(
                        AlertEvent.organization_id == turn.organization_id,
                        AlertEvent.id.in_(event_ids),
                    )
                )
            ).all()
        )
        if event_ids
        else []
    )
    for event in _ordered_rows(events, event_ids):
        candidates.append(
            make_context_item(
                turn.id,
                "alert_event",
                event.id,
                f"事件 {event.title}",
                json_text(
                    {
                        "title": event.title,
                        "severity": event.severity,
                        "status": event.status,
                        "source": event.source,
                        "detail": event.detail,
                        "last_observed_at": event.last_observed_at,
                    }
                ),
                event.last_observed_at,
                8192,
            )
        )

    operation_ids = list(selected.get("operation", []))
    operations = (
        list(
            (
                await session.scalars(
                    select(Operation).where(
                        Operation.organization_id == turn.organization_id,
                        Operation.id.in_(operation_ids),
                    )
                )
            ).all()
        )
        if operation_ids
        else []
    )
    for operation in _ordered_rows(operations, operation_ids):
        candidates.append(
            make_context_item(
                turn.id,
                "operation",
                operation.id,
                f"操作 {operation.action_type}",
                json_text(
                    {
                        "action_type": operation.action_type,
                        "status": operation.status,
                        "risk_level": operation.risk_level,
                        "error_code": operation.error_code,
                        "requested_at": operation.requested_at,
                        "completed_at": operation.completed_at,
                    }
                ),
                operation.updated_at,
                4096,
            )
        )

    diagnostic_ids = list(selected.get("diagnostic_run", []))
    diagnostics = (
        list(
            (
                await session.scalars(
                    select(DiagnosticRun).where(
                        DiagnosticRun.organization_id == turn.organization_id,
                        DiagnosticRun.id.in_(diagnostic_ids),
                    )
                )
            ).all()
        )
        if diagnostic_ids
        else []
    )
    for diagnostic in _ordered_rows(diagnostics, diagnostic_ids):
        candidates.append(
            make_context_item(
                turn.id,
                "diagnostic_run",
                diagnostic.id,
                "诊断记录",
                json_text(
                    {
                        "status": diagnostic.status,
                        "result": diagnostic.result,
                        "error_code": diagnostic.error_code,
                        "completed_at": diagnostic.completed_at,
                    }
                ),
                diagnostic.completed_at or diagnostic.created_at,
                16384,
            )
        )

    evidence_ids = list(selected.get("evidence_item", []))
    evidence = (
        list(
            (
                await session.scalars(
                    select(EvidenceItem)
                    .join(DiagnosticRun, DiagnosticRun.id == EvidenceItem.diagnostic_id)
                    .where(
                        DiagnosticRun.organization_id == turn.organization_id,
                        EvidenceItem.id.in_(evidence_ids),
                    )
                )
            ).all()
        )
        if evidence_ids
        else []
    )
    for item in _ordered_rows(evidence, evidence_ids):
        candidates.append(
            make_context_item(
                turn.id,
                "evidence_item",
                item.id,
                item.source_label,
                item.content,
                item.collected_at,
                4096,
            )
        )

    question_bytes = len(turn.question.encode())
    item_budget = max(settings.conversation_max_context_bytes - question_bytes, 0)
    items, remaining, omitted_by_budget = fit_context_items(candidates, item_budget)
    items = [
        replace(item, snapshot_sha256=snapshot.content_sha256)
        if item.source_type == "fleet_snapshot"
        else item
        for item in items
    ]
    history_rows = list(
        (
            await session.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.session_id == turn.session_id,
                    ConversationTurn.organization_id == turn.organization_id,
                    ConversationTurn.status == "completed",
                    ConversationTurn.id != turn.id,
                )
                .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id)
                .limit(MAX_FLEET_HISTORY)
            )
        ).all()
    )
    history_rows.reverse()
    history: list[dict[str, str]] = []
    history_budget = min(remaining, 32768)
    for previous in history_rows:
        answer = previous.answer or {}
        entry = json_text(
            {
                "question": previous.question,
                "summary": answer.get("summary"),
            }
        )
        entry, _ = truncate_utf8(entry, history_budget)
        if not entry:
            break
        history.append({"turn_id": previous.id, "untrusted_content": entry})
        history_budget -= len(entry.encode())

    manifest = dict(turn.context_manifest)
    manifest.update(
        {
            "context_items": len(items),
            "context_item_bytes": sum(len(item.content.encode()) for item in items),
            "history_turns": len(history),
            "history_bytes": sum(
                len(item["untrusted_content"].encode()) for item in history
            ),
            "total_budget_bytes": settings.conversation_max_context_bytes,
            "total_budget_omitted_items": omitted_by_budget,
        }
    )
    return ConversationContext(
        question=turn.question,
        items=items,
        history=history,
        manifest=manifest,
    )


async def validate_fleet_context(
    session: AsyncSession,
    turn: ConversationTurn,
    organization_id: str,
    items: list[ContextItem],
) -> None:
    snapshot = await session.scalar(
        select(FleetConversationSnapshot).where(
            FleetConversationSnapshot.turn_id == turn.id,
            FleetConversationSnapshot.organization_id == organization_id,
        )
    )
    if snapshot is None:
        raise ConversationFailure(
            "citation_scope_invalid", "Fleet snapshot no longer exists"
        )
    selected = snapshot.selected_source_ids
    allowed: dict[str, set[str]] = {
        key: set(value) for key, value in selected.items() if isinstance(value, list)
    }
    allowed["fleet_snapshot"] = {snapshot.id}

    direct_models = {
        "agent_summary": (Agent, Agent.organization_id),
        "alert_event": (AlertEvent, AlertEvent.organization_id),
        "diagnostic_run": (DiagnosticRun, DiagnosticRun.organization_id),
        "operation": (Operation, Operation.organization_id),
    }
    for source_type, (model, organization_column) in direct_models.items():
        ids = {item.target_id for item in items if item.source_type == source_type}
        if not ids:
            continue
        existing = set(
            (
                await session.scalars(
                    select(model.id).where(
                        organization_column == organization_id,
                        model.id.in_(ids),
                    )
                )
            ).all()
        )
        if existing != ids:
            raise ConversationFailure(
                "citation_scope_invalid", "a Fleet citation is no longer available"
            )
    instance_ids = {
        item.target_id
        for item in items
        if item.source_type == "service_instance_summary"
    }
    if instance_ids:
        existing = set(
            (
                await session.scalars(
                    select(ServiceInstance.id)
                    .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
                    .join(Agent, Agent.id == ServiceInstance.agent_id)
                    .where(
                        ManagedService.organization_id == organization_id,
                        Agent.organization_id == organization_id,
                        ServiceInstance.id.in_(instance_ids),
                    )
                )
            ).all()
        )
        if existing != instance_ids:
            raise ConversationFailure(
                "citation_scope_invalid", "a Fleet service citation is no longer available"
            )
    evidence_ids = {
        item.target_id for item in items if item.source_type == "evidence_item"
    }
    if evidence_ids:
        existing = set(
            (
                await session.scalars(
                    select(EvidenceItem.id)
                    .join(DiagnosticRun, DiagnosticRun.id == EvidenceItem.diagnostic_id)
                    .where(
                        DiagnosticRun.organization_id == organization_id,
                        EvidenceItem.id.in_(evidence_ids),
                    )
                )
            ).all()
        )
        if existing != evidence_ids:
            raise ConversationFailure(
                "citation_scope_invalid", "a Fleet evidence citation is no longer available"
            )
    for item in items:
        if item.target_id not in allowed.get(item.source_type, set()):
            raise ConversationFailure(
                "citation_scope_invalid", "a citation was not selected by the Fleet snapshot"
            )
        if item.source_type == "fleet_snapshot":
            if (
                item.snapshot_sha256 != snapshot.content_sha256
                or _fleet_snapshot_sha256(
                    snapshot.captured_at,
                    snapshot.counts,
                    snapshot.selected_source_ids,
                    snapshot.omitted_counts,
                )
                != snapshot.content_sha256
            ):
                raise ConversationFailure(
                    "citation_scope_invalid", "Fleet snapshot content changed"
                )


@router.get("/fleet/conversation", response_model=FleetConversationView)
async def get_fleet_conversation(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FleetConversationView:
    conversation = await session.scalar(
        select(ConversationSession).where(
            ConversationSession.organization_id == ORGANIZATION_ID,
            ConversationSession.scope_type == "fleet",
        )
    )
    available = settings.conversation_fleet_chat_enabled
    if conversation is None:
        return FleetConversationView(
            session_id=None,
            available=available,
            unavailable_reason=None if available else "feature_disabled",
            turns=[],
        )
    turns = list(
        (
            await session.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.session_id == conversation.id,
                    ConversationTurn.organization_id == ORGANIZATION_ID,
                )
                .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id)
                .limit(MAX_TURNS_RETURNED)
            )
        ).all()
    )
    turns.reverse()
    return FleetConversationView(
        session_id=conversation.id,
        available=available,
        unavailable_reason=None if available else "feature_disabled",
        turns=[await turn_view(session, item, None) for item in turns],
    )


@router.post(
    "/fleet/conversation/turns",
    response_model=ConversationTurnView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def create_fleet_conversation_turn(
    payload: ConversationQuestion,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConversationTurnView:
    if not settings.conversation_fleet_chat_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    await _set_repeatable_read(session)
    conversation = await session.scalar(
        select(ConversationSession).where(
            ConversationSession.organization_id == ORGANIZATION_ID,
            ConversationSession.scope_type == "fleet",
        )
    )
    if conversation is None:
        conversation = ConversationSession(
            organization_id=ORGANIZATION_ID,
            scope_type="fleet",
            event_id=None,
            repository_id=None,
            agent_id=None,
            service_id=None,
            created_by="local-admin",
        )
        try:
            async with session.begin_nested():
                session.add(conversation)
                await session.flush()
        except IntegrityError:
            conversation = await session.scalar(
                select(ConversationSession).where(
                    ConversationSession.organization_id == ORGANIZATION_ID,
                    ConversationSession.scope_type == "fleet",
                )
            )
            if conversation is None:
                raise
    existing = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.session_id == conversation.id,
            ConversationTurn.client_request_id == payload.client_request_id,
            ConversationTurn.organization_id == ORGANIZATION_ID,
        )
    )
    if existing is not None:
        return await turn_view(session, existing, None)
    active = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.session_id == conversation.id,
            ConversationTurn.organization_id == ORGANIZATION_ID,
            ConversationTurn.status.in_(["pending", "running"]),
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="a conversation turn is already active")
    safe_question, _ = redact_text(payload.question)
    turn = ConversationTurn(
        organization_id=ORGANIZATION_ID,
        session_id=conversation.id,
        client_request_id=payload.client_request_id,
        question=safe_question,
        status="pending",
        provider=settings.conversation_provider,
        context_manifest={},
    )
    session.add(turn)
    try:
        await session.flush()
        await capture_fleet_snapshot(session, turn, settings)
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.session_id == conversation.id,
                ConversationTurn.client_request_id == payload.client_request_id,
                ConversationTurn.organization_id == ORGANIZATION_ID,
            )
        )
        if existing is not None:
            return await turn_view(session, existing, None)
        raise HTTPException(
            status_code=409, detail="a conversation turn is already active"
        ) from error
    background_tasks.add_task(
        run_conversation_turn, turn.id, ORGANIZATION_ID, settings
    )
    return await turn_view(session, turn, None)


def _encode_cursor(occurred_at: datetime, identifier: str) -> str:
    value = f"{occurred_at.isoformat()}|{identifier}".encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        timestamp, identifier = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), identifier
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="invalid cursor") from error


@router.get("/events/{event_id}/history", response_model=EventHistoryView)
async def get_event_history(
    event_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EventHistoryView:
    if not settings.conversation_insights_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    items: list[EventHistoryItemView] = [
        EventHistoryItemView(
            id=event.id,
            item_type="event",
            status=event.status,
            summary=redact_text(event.title)[0],
            occurred_at=event.last_observed_at,
            href=f"/events/{event.id}",
        )
    ]
    diagnostics = list(
        (
            await session.scalars(
                select(DiagnosticRun).where(
                    DiagnosticRun.organization_id == ORGANIZATION_ID,
                    DiagnosticRun.event_id == event.id,
                )
            )
        ).all()
    )
    for diagnostic in diagnostics:
        result = diagnostic.result if isinstance(diagnostic.result, dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), str) else "诊断记录"
        items.append(
            EventHistoryItemView(
                id=diagnostic.id,
                item_type="diagnostic",
                status=diagnostic.status,
                summary=truncate_utf8(redact_text(summary)[0], 512)[0],
                occurred_at=diagnostic.completed_at or diagnostic.created_at,
                href=f"/events/{event.id}",
            )
        )
    conversation = await session.scalar(
        select(ConversationSession).where(
            ConversationSession.organization_id == ORGANIZATION_ID,
            ConversationSession.scope_type == "event",
            ConversationSession.event_id == event.id,
        )
    )
    if conversation is not None:
        turns = list(
            (
                await session.scalars(
                    select(ConversationTurn).where(
                        ConversationTurn.organization_id == ORGANIZATION_ID,
                        ConversationTurn.session_id == conversation.id,
                    )
                )
            ).all()
        )
        for turn in turns:
            answer = turn.answer if isinstance(turn.answer, dict) else {}
            summary = (
                answer.get("summary")
                if isinstance(answer.get("summary"), str)
                else "会话轮次"
            )
            items.append(
                EventHistoryItemView(
                    id=turn.id,
                    item_type="conversation",
                    status=turn.status,
                    summary=truncate_utf8(redact_text(summary)[0], 512)[0],
                    occurred_at=turn.completed_at or turn.created_at,
                    href=f"/events/{event.id}",
                )
            )
    diagnostic_ids = [item.id for item in diagnostics]
    operation_filter = [Operation.source_event_id == event.id]
    if diagnostic_ids:
        operation_filter.append(Operation.source_diagnostic_id.in_(diagnostic_ids))
    operations = list(
        (
            await session.scalars(
                select(Operation).where(
                    Operation.organization_id == ORGANIZATION_ID,
                    or_(*operation_filter),
                )
            )
        ).all()
    )
    for operation in operations:
        items.append(
            EventHistoryItemView(
                id=operation.id,
                item_type="operation",
                status=operation.status,
                summary=f"{operation.action_type} · {operation.status}",
                occurred_at=operation.completed_at or operation.requested_at,
                href=f"/operations/{operation.id}",
            )
        )
    items.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
    decoded = _decode_cursor(cursor)
    if decoded is not None:
        items = [item for item in items if (item.occurred_at, item.id) < decoded]
    page = items[:limit]
    next_cursor = (
        _encode_cursor(page[-1].occurred_at, page[-1].id)
        if len(items) > limit and page
        else None
    )
    return EventHistoryView(event_id=event.id, items=page, next_cursor=next_cursor)


async def _service_ids_for_events(
    session: AsyncSession, events: list[AlertEvent]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for event in events:
        if event.source != "service" or not event.service_kind or not event.service_key:
            continue
        service_id = await session.scalar(
            select(ServiceInstance.service_id)
            .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
            .join(Agent, Agent.id == ServiceInstance.agent_id)
            .where(
                ServiceInstance.agent_id == event.agent_id,
                ServiceInstance.service_kind == event.service_kind,
                ServiceInstance.service_key == event.service_key,
                ManagedService.organization_id == ORGANIZATION_ID,
                Agent.organization_id == ORGANIZATION_ID,
            )
        )
        if service_id:
            result[event.id] = service_id
    return result


@router.get(
    "/events/{event_id}/similar-events", response_model=SimilarEventsView
)
async def get_similar_events(
    event_id: str,
    limit: int = Query(default=10, ge=1, le=10),
    cursor: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SimilarEventsView:
    if not settings.conversation_insights_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    candidates = list(
        (
            await session.scalars(
                select(AlertEvent)
                .where(
                    AlertEvent.organization_id == ORGANIZATION_ID,
                    AlertEvent.id != event.id,
                    AlertEvent.last_observed_at >= utcnow() - timedelta(days=180),
                )
                .order_by(AlertEvent.last_observed_at.desc(), AlertEvent.id)
                .limit(200)
            )
        ).all()
    )
    service_ids = await _service_ids_for_events(session, [event, *candidates])
    current_service = service_ids.get(event.id)
    scored: list[tuple[int, AlertEvent, list[str], bool, bool]] = []
    for candidate in candidates:
        reasons: list[str] = []
        score = 0
        same_service = bool(
            current_service and service_ids.get(candidate.id) == current_service
        )
        same_agent = candidate.agent_id == event.agent_id
        if same_service:
            score += 5
            reasons.append("same_managed_service")
        if same_agent:
            score += 3
            reasons.append("same_agent")
        if candidate.fingerprint == event.fingerprint:
            score += 4
            reasons.append("same_fingerprint")
        if candidate.source == event.source:
            score += 2
            reasons.append("same_source")
        if candidate.severity == event.severity:
            score += 1
            reasons.append("same_severity")
        if not reasons:
            continue
        scored.append((score, candidate, reasons, same_agent, same_service))
    scored.sort(key=lambda row: (row[0], row[1].last_observed_at, row[1].id), reverse=True)
    decoded = _decode_cursor(cursor)
    if decoded is not None:
        scored = [
            row
            for row in scored
            if (row[1].last_observed_at, row[1].id) < decoded
        ]
    views: list[SimilarEventView] = []
    page_rows = scored[:limit]
    for score, candidate, reasons, same_agent, same_service in page_rows:
        diagnostic = await session.scalar(
            select(DiagnosticRun)
            .where(
                DiagnosticRun.organization_id == ORGANIZATION_ID,
                DiagnosticRun.event_id == candidate.id,
                DiagnosticRun.status == "completed",
            )
            .order_by(DiagnosticRun.completed_at.desc(), DiagnosticRun.id)
            .limit(1)
        )
        diagnostic_summary = None
        if diagnostic and isinstance(diagnostic.result, dict):
            value = diagnostic.result.get("summary")
            if isinstance(value, str):
                diagnostic_summary = truncate_utf8(redact_text(value)[0], 512)[0]
        views.append(
            SimilarEventView(
                id=candidate.id,
                title=truncate_utf8(redact_text(candidate.title)[0], 255)[0],
                severity=candidate.severity,
                status=candidate.status,
                score_band="high" if score >= 7 else ("medium" if score >= 4 else "low"),
                match_reasons=reasons,
                same_agent=same_agent,
                same_service=same_service,
                diagnostic_summary=diagnostic_summary,
                last_observed_at=candidate.last_observed_at,
                href=f"/events/{candidate.id}",
            )
        )
    next_cursor = (
        _encode_cursor(page_rows[-1][1].last_observed_at, page_rows[-1][1].id)
        if len(scored) > limit and page_rows
        else None
    )
    return SimilarEventsView(
        event_id=event.id, items=views, next_cursor=next_cursor
    )


@router.put(
    "/conversation-turns/{turn_id}/feedback",
    response_model=ConversationFeedbackView,
    dependencies=[Depends(require_admin)],
)
async def put_conversation_feedback(
    turn_id: str,
    payload: ConversationFeedbackUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConversationFeedbackView:
    if not settings.conversation_insights_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    turn = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.id == turn_id,
            ConversationTurn.organization_id == ORGANIZATION_ID,
            ConversationTurn.status == "completed",
        )
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="conversation turn not found")
    feedback = await session.scalar(
        select(ConversationTurnFeedback).where(
            ConversationTurnFeedback.organization_id == ORGANIZATION_ID,
            ConversationTurnFeedback.turn_id == turn.id,
            ConversationTurnFeedback.created_by == "local-admin",
        )
    )
    safe_comment = redact_text(payload.comment)[0] if payload.comment else None
    if feedback is None:
        feedback = ConversationTurnFeedback(
            organization_id=ORGANIZATION_ID,
            turn_id=turn.id,
            created_by="local-admin",
            rating=payload.rating,
            reason_code=payload.reason_code,
            comment=safe_comment,
        )
        session.add(feedback)
    else:
        feedback.rating = payload.rating
        feedback.reason_code = payload.reason_code
        feedback.comment = safe_comment
        feedback.updated_at = utcnow()
    await session.commit()
    await session.refresh(feedback)
    return ConversationFeedbackView(
        turn_id=feedback.turn_id,
        rating=feedback.rating,
        reason_code=feedback.reason_code,
        comment=feedback.comment,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def _safe_result_lists(result: object) -> tuple[list[str], list[str], list[str]]:
    if not isinstance(result, dict):
        return [], [], []
    facts: list[str] = []
    inferences: list[str] = []
    missing: list[str] = []
    for raw in result.get("facts", []):
        if isinstance(raw, dict) and isinstance(raw.get("statement"), str):
            facts.append(truncate_utf8(redact_text(raw["statement"])[0], 1000)[0])
    for raw in result.get("inferences", []):
        if isinstance(raw, dict) and isinstance(raw.get("statement"), str):
            inferences.append(truncate_utf8(redact_text(raw["statement"])[0], 1000)[0])
    for raw in result.get("missing_evidence", []):
        if isinstance(raw, str):
            missing.append(truncate_utf8(redact_text(raw)[0], 1000)[0])
    return facts[:64], inferences[:64], missing[:64]


@router.get("/events/{event_id}/review", response_model=EventReviewView)
async def get_event_review(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EventReviewView:
    if not settings.conversation_review_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    event = await scoped_event(session, event_id, ORGANIZATION_ID)
    diagnostics = list(
        (
            await session.scalars(
                select(DiagnosticRun)
                .where(
                    DiagnosticRun.organization_id == ORGANIZATION_ID,
                    DiagnosticRun.event_id == event.id,
                    DiagnosticRun.status == "completed",
                )
                .order_by(DiagnosticRun.completed_at, DiagnosticRun.id)
            )
        ).all()
    )
    facts = [
        f"事件状态为 {event.status}，严重级别为 {event.severity}。",
        f"累计观测 {event.observation_count} 次。",
    ]
    inferences: list[str] = []
    missing: list[str] = []
    sources = [
        EventReviewSourceView(
            source_type="alert_event",
            source_id=event.id,
            label="告警事件",
            occurred_at=event.last_observed_at,
            href=f"/events/{event.id}",
        )
    ]
    for diagnostic in diagnostics:
        diag_facts, diag_inferences, diag_missing = _safe_result_lists(diagnostic.result)
        facts.extend(diag_facts)
        inferences.extend(diag_inferences)
        missing.extend(diag_missing)
        sources.append(
            EventReviewSourceView(
                source_type="diagnostic_run",
                source_id=diagnostic.id,
                label="诊断记录",
                occurred_at=diagnostic.completed_at or diagnostic.created_at,
                href=f"/events/{event.id}",
            )
        )
    diagnostic_ids = [item.id for item in diagnostics]
    filters = [Operation.source_event_id == event.id]
    if diagnostic_ids:
        filters.append(Operation.source_diagnostic_id.in_(diagnostic_ids))
    operations = list(
        (
            await session.scalars(
                select(Operation)
                .where(Operation.organization_id == ORGANIZATION_ID, or_(*filters))
                .order_by(Operation.requested_at, Operation.id)
            )
        ).all()
    )
    operation_results = [
        f"{item.action_type}: {item.status}" for item in operations
    ]
    for operation in operations:
        sources.append(
            EventReviewSourceView(
                source_type="operation",
                source_id=operation.id,
                label=f"操作 {operation.action_type}",
                occurred_at=operation.completed_at or operation.requested_at,
                href=f"/operations/{operation.id}",
            )
        )
    conversation = await session.scalar(
        select(ConversationSession).where(
            ConversationSession.organization_id == ORGANIZATION_ID,
            ConversationSession.scope_type == "event",
            ConversationSession.event_id == event.id,
        )
    )
    if conversation is not None:
        turns = list(
            (
                await session.scalars(
                    select(ConversationTurn).where(
                        ConversationTurn.organization_id == ORGANIZATION_ID,
                        ConversationTurn.session_id == conversation.id,
                        ConversationTurn.status == "completed",
                    )
                )
            ).all()
        )
        for turn in turns:
            turn_facts, turn_inferences, turn_missing = _safe_result_lists(turn.answer)
            facts.extend(turn_facts)
            inferences.extend(turn_inferences)
            missing.extend(turn_missing)
            sources.append(
                EventReviewSourceView(
                    source_type="conversation_turn",
                    source_id=turn.id,
                    label="事件会话结论",
                    occurred_at=turn.completed_at or turn.created_at,
                    href=f"/events/{event.id}",
                )
            )
    provisional = event.status != "resolved"
    summary = (
        "这是尚未解决事件的临时复盘，只汇总当前控制平面记录。"
        if provisional
        else "这是已解决事件的只读复盘，事实、推断与操作结果保持分区。"
    )
    return EventReviewView(
        event_id=event.id,
        provisional=provisional,
        summary=summary,
        facts=facts[:64],
        inferences=inferences[:64],
        operation_results=operation_results[:64],
        missing_evidence=missing[:64],
        sources=sources[:100],
    )


async def _derive_runbook_scope(
    session: AsyncSession, conversation: ConversationSession
) -> tuple[str | None, str | None]:
    if conversation.scope_type == "service":
        return None, conversation.service_id
    if conversation.scope_type != "event" or not conversation.event_id:
        return None, None
    event = await scoped_event(session, conversation.event_id, ORGANIZATION_ID)
    service_id = None
    if event.source == "service" and event.service_kind and event.service_key:
        service_id = await session.scalar(
            select(ServiceInstance.service_id)
            .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
            .join(Agent, Agent.id == ServiceInstance.agent_id)
            .where(
                ServiceInstance.agent_id == event.agent_id,
                ServiceInstance.service_kind == event.service_kind,
                ServiceInstance.service_key == event.service_key,
                ManagedService.organization_id == ORGANIZATION_ID,
                Agent.organization_id == ORGANIZATION_ID,
            )
        )
    return event.id, service_id


@router.post(
    "/conversation-turns/{turn_id}/runbook-drafts",
    response_model=RunbookDraftView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_runbook_draft(
    turn_id: str,
    payload: RunbookDraftCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunbookDraftView:
    if not settings.conversation_review_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    row = (
        await session.execute(
            select(ConversationTurn, ConversationSession)
            .join(
                ConversationSession,
                (ConversationSession.id == ConversationTurn.session_id)
                & (ConversationSession.organization_id == ConversationTurn.organization_id),
            )
            .where(
                ConversationTurn.id == turn_id,
                ConversationTurn.organization_id == ORGANIZATION_ID,
                ConversationTurn.status == "completed",
                ConversationSession.organization_id == ORGANIZATION_ID,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="conversation turn not found")
    turn, conversation = row
    existing = await session.scalar(
        select(RunbookDraft).where(
            RunbookDraft.organization_id == ORGANIZATION_ID,
            RunbookDraft.source_turn_id == turn.id,
            RunbookDraft.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        return await runbook_draft_view(session, existing)
    try:
        answer = ConversationAnswer.model_validate(turn.answer)
    except ValidationError as error:
        raise HTTPException(status_code=409, detail="source_answer_invalid") from error
    if payload.recommendation_index >= len(answer.recommendations):
        raise HTTPException(status_code=422, detail="recommendation_index_out_of_range")
    recommendation = answer.recommendations[payload.recommendation_index]
    citation_rows = list(
        (
            await session.scalars(
                select(ConversationCitation).where(
                    ConversationCitation.organization_id == ORGANIZATION_ID,
                    ConversationCitation.turn_id == turn.id,
                    ConversationCitation.citation_id.in_(recommendation.citation_ids),
                )
            )
        ).all()
    )
    rows_by_alias = {item.citation_id: item for item in citation_rows}
    if any(alias not in rows_by_alias for alias in recommendation.citation_ids):
        raise HTTPException(status_code=409, detail="source_citation_unavailable")
    if any(
        (item.source_type == "repository_file" and item.repository_file_id is None)
        or (item.source_type == "fleet_snapshot" and item.fleet_snapshot_id is None)
        for item in rows_by_alias.values()
    ):
        raise HTTPException(status_code=409, detail="source_citation_unavailable")
    source_event_id, service_id = await _derive_runbook_scope(session, conversation)
    safe_action = truncate_utf8(redact_text(recommendation.action)[0], 1000)[0]
    title = truncate_utf8(safe_action, 255)[0]
    draft = RunbookDraft(
        organization_id=ORGANIZATION_ID,
        source_turn_id=turn.id,
        source_turn_organization_id=ORGANIZATION_ID,
        source_event_id=source_event_id,
        source_event_organization_id=(ORGANIZATION_ID if source_event_id else None),
        service_id=service_id,
        service_organization_id=(ORGANIZATION_ID if service_id else None),
        client_request_id=payload.client_request_id,
        title=title,
        content={
            "schema_version": "m5.7-runbook-draft-v1",
            "objective": safe_action,
            "prerequisites": ["人工核对来源证据与当前环境。"],
            "display_steps": [safe_action],
            "risk": recommendation.risk,
            "requires_confirmation": True,
            "executable": False,
        },
        source_citation_ids=[rows_by_alias[alias].id for alias in recommendation.citation_ids],
        status="draft",
        created_by="local-admin",
    )
    session.add(draft)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(RunbookDraft).where(
                RunbookDraft.organization_id == ORGANIZATION_ID,
                RunbookDraft.source_turn_id == turn.id,
                RunbookDraft.client_request_id == payload.client_request_id,
            )
        )
        if existing is None:
            raise
        return await runbook_draft_view(session, existing)
    await session.refresh(draft)
    return await runbook_draft_view(session, draft)


async def runbook_draft_view(
    session: AsyncSession, draft: RunbookDraft
) -> RunbookDraftView:
    source_turn = None
    if draft.source_turn_id:
        source_turn = await session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.id == draft.source_turn_id,
                ConversationTurn.organization_id == draft.organization_id,
            )
        )
    citation_ids = list(draft.source_citation_ids or [])[:16]
    rows = (
        list(
            (
                await session.scalars(
                    select(ConversationCitation).where(
                        ConversationCitation.id.in_(citation_ids),
                        ConversationCitation.organization_id == draft.organization_id,
                        ConversationCitation.turn_id == draft.source_turn_id,
                    )
                )
            ).all()
        )
        if source_turn is not None and citation_ids
        else []
    )
    row_map = {item.id: item for item in rows}
    citation_views: list[RunbookDraftCitationView] = []
    for citation_id in citation_ids:
        item = row_map.get(citation_id)
        source_available = bool(
            item
            and not (
                item.source_type == "repository_file" and item.repository_file_id is None
            )
            and not (
                item.source_type == "fleet_snapshot" and item.fleet_snapshot_id is None
            )
        )
        citation_views.append(
            RunbookDraftCitationView(
                id=citation_id,
                source_type=item.source_type if item else None,
                source_label=(
                    item.source_label
                    if source_available and item is not None
                    else f"引用已失效 ({citation_id[:8]})"
                ),
                href=(
                    citation_href(item, draft.source_event_id)
                    if source_available and item
                    else None
                ),
                available=source_available,
            )
        )
    return RunbookDraftView(
        id=draft.id,
        source_turn_id=draft.source_turn_id,
        source_event_id=draft.source_event_id,
        service_id=draft.service_id,
        title=draft.title,
        content=draft.content,
        status="draft",
        source_available=source_turn is not None,
        citations=citation_views,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.get("/runbook-drafts/{draft_id}", response_model=RunbookDraftView)
async def get_runbook_draft(
    draft_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunbookDraftView:
    if not settings.conversation_review_enabled:
        raise HTTPException(status_code=403, detail="feature_disabled")
    draft = await session.scalar(
        select(RunbookDraft).where(
            RunbookDraft.id == draft_id,
            RunbookDraft.organization_id == ORGANIZATION_ID,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="runbook draft not found")
    return await runbook_draft_view(session, draft)
