import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.conversation_operations as handoff_module
from app.config import Settings
from app.models import (
    AlertEvent,
    ConversationSession,
    ConversationTurn,
    ManagedService,
    Operation,
    ServiceInstance,
)
from app.schemas import ConversationRestartPlanCreate


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def event() -> AlertEvent:
    now = now_utc()
    return AlertEvent(
        id="event-1",
        organization_id="local",
        agent_id="agent-1",
        fingerprint="f" * 64,
        source="service",
        service_kind="docker",
        service_key="compose:demo:api:1",
        title="API unhealthy",
        severity="warning",
        status="firing",
        observation_count=2,
        first_observed_at=now,
        last_observed_at=now,
    )


def answer() -> dict:
    return {
        "summary": "A bounded answer",
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "missing_evidence": [],
    }


def turn(status: str = "completed") -> ConversationTurn:
    now = now_utc()
    return ConversationTurn(
        id="turn-1",
        organization_id="local",
        session_id="session-1",
        client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
        question="修复它",
        status=status,
        provider="deterministic",
        answer=answer() if status == "completed" else None,
        context_manifest={"selected_items": 1},
        created_at=now,
        completed_at=now if status == "completed" else None,
    )


def operation() -> Operation:
    now = now_utc()
    return Operation(
        id="operation-1",
        organization_id="local",
        instance_id="instance-1",
        agent_id="agent-1",
        source_event_id="event-1",
        source_conversation_turn_id="turn-1",
        conversation_request_id="9fd98744-1d93-4555-b019-e075b0453f35",
        action_type="docker_restart",
        status="awaiting_confirmation",
        active_key="instance-1:write",
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="restart",
        plan_snapshot={},
        precheck_result={"passed": True},
        verification_policy={},
        idempotency_key="operation-idempotency",
        expires_at=now + timedelta(minutes=5),
        requested_at=now,
        updated_at=now,
    )


def test_restart_plan_request_forbids_all_executable_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationRestartPlanCreate.model_validate(
            {
                "client_request_id": "9fd98744-1d93-4555-b019-e075b0453f35",
                "expires_in_seconds": 300,
                "instance_id": "attacker-selected",
                "action_type": "docker_compose_deploy",
                "command": "rm -rf /",
            }
        )


def test_disabled_handoff_fails_before_creating_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    monkeypatch.setattr(handoff_module, "scoped_event", AsyncMock(return_value=event()))
    build = AsyncMock()
    monkeypatch.setattr(handoff_module, "build_restart_plan", build)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            handoff_module.create_conversation_restart_plan(
                "event-1",
                "turn-1",
                ConversationRestartPlanCreate(
                    client_request_id="9fd98744-1d93-4555-b019-e075b0453f35"
                ),
                session,
                Settings(conversation_operation_handoff_enabled=False),
            )
        )

    assert error.value.status_code == 409
    assert error.value.detail == "conversation_operation_handoff_disabled"
    build.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_handoff_derives_fixed_restart_and_stops_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_event = event()
    current_turn = turn()
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key=current_event.service_key or "",
        restart_enabled=True,
    )
    managed = ManagedService(
        id="service-1",
        organization_id="local",
        name="API",
        criticality="non_critical",
    )
    created = operation()
    session = AsyncMock()
    session.scalar.return_value = None
    monkeypatch.setattr(
        handoff_module,
        "scoped_event",
        AsyncMock(return_value=current_event),
    )
    monkeypatch.setattr(
        handoff_module,
        "_scoped_completed_turn",
        AsyncMock(
            return_value=(
                current_turn,
                handoff_module.ConversationAnswer.model_validate(answer()),
            )
        ),
    )
    monkeypatch.setattr(
        handoff_module,
        "_event_instance",
        AsyncMock(return_value=(instance, managed)),
    )
    build = AsyncMock(return_value=created)
    monkeypatch.setattr(handoff_module, "build_restart_plan", build)
    view = AsyncMock(return_value="operation-view")
    monkeypatch.setattr(handoff_module, "_operation_view", view)

    result = asyncio.run(
        handoff_module.create_conversation_restart_plan(
            current_event.id,
            current_turn.id,
            ConversationRestartPlanCreate(
                client_request_id="9fd98744-1d93-4555-b019-e075b0453f35",
                expires_in_seconds=300,
            ),
            session,
            Settings(conversation_operation_handoff_enabled=True),
        )
    )

    assert result == "operation-view"
    source = build.await_args.kwargs["source_metadata"]
    assert source["turn_id"] == current_turn.id
    assert source["conversation_request_id"] == "9fd98744-1d93-4555-b019-e075b0453f35"
    assert source["conversation_source"]["handoff_kind"] == "explicit_user_restart_plan"
    assert set(source["conversation_source"]) == {
        "turn_id",
        "answer_sha256",
        "context_manifest_sha256",
        "handoff_kind",
    }
    assert current_turn.question not in str(source)
    assert build.await_args.args[1] is instance
    assert created.status == "awaiting_confirmation"
    assert created.task_signature is None
    assert created.task_nonce is None


def test_request_id_reuse_in_other_scope_is_a_non_disclosing_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = operation()
    existing.source_event_id = "other-event"
    session = AsyncMock()
    session.scalar.return_value = existing
    monkeypatch.setattr(handoff_module, "scoped_event", AsyncMock(return_value=event()))
    monkeypatch.setattr(
        handoff_module,
        "_scoped_completed_turn",
        AsyncMock(
            return_value=(
                turn(),
                handoff_module.ConversationAnswer.model_validate(answer()),
            )
        ),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            handoff_module.create_conversation_restart_plan(
                "event-1",
                "turn-1",
                ConversationRestartPlanCreate(
                    client_request_id="9fd98744-1d93-4555-b019-e075b0453f35"
                ),
                session,
                Settings(conversation_operation_handoff_enabled=True),
            )
        )

    assert error.value.status_code == 409
    assert error.value.detail == "conversation request id is already in use"


@pytest.mark.parametrize("turn_status", ["pending", "running", "failed"])
def test_non_completed_turn_cannot_handoff(turn_status: str) -> None:
    conversation = ConversationSession(
        id="session-1",
        organization_id="local",
        scope_type="event",
        event_id="event-1",
        created_by="local-admin",
    )
    session = AsyncMock()
    session.scalar.side_effect = [conversation, turn(turn_status)]

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            handoff_module._scoped_completed_turn(
                session,
                "event-1",
                "turn-1",
                organization_id="local",
            )
        )

    assert error.value.status_code == 409


def test_candidate_read_is_static_and_has_no_operation_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_event = event()
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key=current_event.service_key or "",
        restart_enabled=True,
    )
    managed = ManagedService(
        id="service-1",
        organization_id="local",
        name="API",
        criticality="non_critical",
    )
    session = AsyncMock()
    session.add = MagicMock()
    monkeypatch.setattr(handoff_module, "scoped_event", AsyncMock(return_value=current_event))
    monkeypatch.setattr(
        handoff_module,
        "_event_instance",
        AsyncMock(return_value=(instance, managed)),
    )

    result = asyncio.run(
        handoff_module.conversation_operation_candidates(
            "event-1",
            session,
            Settings(conversation_operation_handoff_enabled=True),
        )
    )

    assert result.candidates[0].available is True
    assert result.candidates[0].action_type == "docker_restart"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
