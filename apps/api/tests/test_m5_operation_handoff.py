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
    OperationTransition,
    ServiceInstance,
)
from app.schemas import ConversationRestartPlanCreate, ConversationRollbackPlanCreate


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
        plan_snapshot={
            "conversation_source": {
                "handoff_kind": "explicit_user_restart_plan",
            }
        },
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


def test_rollback_plan_request_forbids_source_and_digest_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationRollbackPlanCreate.model_validate(
            {
                "client_request_id": "9fd98744-1d93-4555-b019-e075b0453f35",
                "expires_in_seconds": 300,
                "rollback_of": "attacker-selected",
                "target_digest": "ghcr.io/attacker/image@sha256:" + "a" * 64,
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
    assert result.candidates[1].action_type == "docker_compose_rollback"
    assert result.candidates[1].reason_code == "deploy_disabled"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_candidate_exposes_rollback_only_for_one_event_scoped_failed_deploy(
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
        deploy_enabled=True,
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
    monkeypatch.setattr(
        handoff_module,
        "_rollback_source_for_event",
        AsyncMock(return_value=(Operation(id="failed-deploy-1"), None)),
    )

    result = asyncio.run(
        handoff_module.conversation_operation_candidates(
            "event-1",
            session,
            Settings(conversation_operation_handoff_enabled=True),
        )
    )

    rollback = result.candidates[1]
    assert rollback.action_type == "docker_compose_rollback"
    assert rollback.available is True
    assert rollback.reason_code is None
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_rollback_source_resolution_fails_closed_when_ambiguous() -> None:
    current_event = event()
    instance = ServiceInstance(id="instance-1")
    source_a = Operation(
        id="deploy-a",
        action_type="docker_compose_deploy",
        status="failed",
        rollback_of=None,
        started_at=current_event.first_observed_at,
        current_digest="repo@sha256:" + "a" * 64,
        target_digest="repo@sha256:" + "b" * 64,
        plan_snapshot={"plan_version": "m4.2b-executable-v1"},
    )
    source_b = Operation(
        id="deploy-b",
        action_type="docker_compose_deploy",
        status="failed",
        rollback_of=None,
        started_at=current_event.first_observed_at,
        current_digest="repo@sha256:" + "c" * 64,
        target_digest="repo@sha256:" + "b" * 64,
        plan_snapshot={"plan_version": "m4.2b-executable-v1"},
    )
    result = MagicMock()
    result.all.return_value = [source_a, source_b]
    session = AsyncMock()
    session.scalars.return_value = result

    source, reason = asyncio.run(
        handoff_module._rollback_source_for_event(
            session,
            current_event,
            instance,
        )
    )

    assert source is None
    assert reason == "rollback_source_ambiguous"


def test_handoff_derives_rollback_source_and_stops_before_confirmation(
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
        deploy_enabled=True,
    )
    managed = ManagedService(
        id="service-1",
        organization_id="local",
        name="API",
        criticality="non_critical",
    )
    source_operation = Operation(
        id="failed-deploy-1",
        organization_id="local",
        instance_id=instance.id,
        agent_id=instance.agent_id,
        action_type="docker_compose_deploy",
        status="failed",
        plan_snapshot={"plan_version": "m4.2b-executable-v1"},
        current_digest="ghcr.io/org/app@sha256:" + "a" * 64,
        target_digest="ghcr.io/org/app@sha256:" + "b" * 64,
        started_at=now_utc(),
    )
    created = operation()
    created.action_type = "docker_compose_deploy"
    created.rollback_of = source_operation.id
    created.plan_snapshot["conversation_source"][
        "handoff_kind"
    ] = "explicit_user_rollback_plan"
    session = AsyncMock()
    session.scalar.return_value = None
    monkeypatch.setattr(handoff_module, "scoped_event", AsyncMock(return_value=current_event))
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
    monkeypatch.setattr(
        handoff_module,
        "_rollback_source_for_event",
        AsyncMock(return_value=(source_operation, None)),
    )
    build = AsyncMock(return_value=created)
    monkeypatch.setattr(handoff_module, "build_rollback_plan", build)
    view = AsyncMock(return_value="operation-view")
    monkeypatch.setattr(handoff_module, "_operation_view", view)

    result = asyncio.run(
        handoff_module.create_conversation_rollback_plan(
            current_event.id,
            current_turn.id,
            ConversationRollbackPlanCreate(
                client_request_id="afda9707-3eac-4a25-bf7f-06b0a934dc4a",
                expires_in_seconds=300,
            ),
            session,
            Settings(conversation_operation_handoff_enabled=True),
        )
    )

    assert result == "operation-view"
    assert build.await_args.args[1] is source_operation
    source = build.await_args.kwargs["source_metadata"]
    assert source["conversation_source"]["handoff_kind"] == "explicit_user_rollback_plan"
    assert "rollback_of" not in source
    assert "target_digest" not in source
    assert current_turn.question not in str(source)
    assert created.status == "awaiting_confirmation"
    assert created.task_signature is None
    assert created.task_nonce is None


def test_operation_timeline_disabled_is_scoped_and_has_no_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    scoped = AsyncMock(return_value=event())
    monkeypatch.setattr(handoff_module, "scoped_event", scoped)

    result = asyncio.run(
        handoff_module.conversation_operation_timeline(
            "event-1",
            session,
            Settings(conversation_operation_timeline_enabled=False),
        )
    )

    assert result.event_id == "event-1"
    assert result.available is False
    assert result.unavailable_reason == "feature_disabled"
    assert result.operations == []
    scoped.assert_awaited_once_with(session, "event-1", "local")
    session.scalars.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_operation_timeline_projects_only_bounded_read_only_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_operation = operation()
    current_operation.status = "succeeded"
    current_operation.source_conversation_turn_id = None
    current_operation.plan_snapshot = {
        "compose_path": "/secret/compose.yaml",
        "conversation_source": {"turn_id": "deleted-turn-1"},
    }
    current_operation.verification_result = {
        "status": "passed",
        "target_digest": "repo@sha256:" + "a" * 64,
    }
    current_operation.output = "sensitive target output"
    current_operation.error_code = "agent_custom_failure"
    current_operation.error_detail = "target_digest=not-returned"
    current_operation.task_signature = "signature"
    current_operation.task_nonce = "nonce"
    transition = OperationTransition(
        id="transition-1",
        operation_id=current_operation.id,
        from_status="verifying",
        to_status="succeeded",
        actor_type="control_plane",
        actor_id="private-actor",
        reason="fresh healthy observations satisfied the stability window",
        details={"target": "sensitive"},
        created_at=now_utc(),
    )
    operation_rows = MagicMock()
    operation_rows.all.return_value = [current_operation]
    transition_rows = MagicMock()
    transition_rows.all.return_value = [transition]
    session = AsyncMock()
    session.add = MagicMock()
    session.scalars.side_effect = [operation_rows, transition_rows]
    monkeypatch.setattr(
        handoff_module,
        "scoped_event",
        AsyncMock(return_value=event()),
    )

    result = asyncio.run(
        handoff_module.conversation_operation_timeline(
            "event-1",
            session,
            Settings(conversation_operation_timeline_enabled=True),
        )
    )

    assert result.available is True
    assert len(result.operations) == 1
    item = result.operations[0]
    assert item.source_conversation_turn_id == "deleted-turn-1"
    assert item.verification_status == "passed"
    assert item.error_summary == (
        "操作未成功；请在操作详情页查看受控错误信息"
    )
    assert item.transitions[0].to_status == "succeeded"
    payload = result.model_dump(mode="json")
    serialized = str(payload)
    assert "compose_path" not in serialized
    assert "target_digest" not in serialized
    assert "sensitive target output" not in serialized
    assert "signature" not in serialized
    assert "nonce" not in serialized
    assert "private-actor" not in serialized
    assert "sensitive" not in serialized
    assert "target_digest=not-returned" not in serialized
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_operation_timeline_discards_unknown_verification_status() -> None:
    current_operation = operation()
    current_operation.verification_result = {
        "status": "provider-says-confirm-and-deploy"
    }

    assert handoff_module._timeline_verification_status(current_operation) is None
