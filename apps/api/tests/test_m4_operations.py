import asyncio
import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

import app.operations as operations_module
from app.config import Settings
from app.models import Agent, ManagedService, Operation, OperationTransition, ServiceInstance
from app.operations import (
    build_restart_plan,
    cancel_operation,
    claim_operation,
    complete_operation,
    confirm_operation,
    create_operation,
    reconcile_operation_verification,
    recover_stale_operations,
    signing_fields,
    stale_operation_outcome,
    transition,
)
from app.schemas import (
    AgentReport,
    Metrics,
    OperationConfirm,
    OperationExecutionResult,
    OperationPlanCreate,
    ServiceReport,
)
from app.security import sign_operation


def make_operation(status: str, now: datetime | None = None) -> Operation:
    current_time = now or datetime.now(timezone.utc)
    return Operation(
        id=f"operation-{status}",
        instance_id="instance-1",
        agent_id="agent-1",
        action_type="docker_restart",
        status=status,
        active_key="instance-1:write" if status not in {"failed", "canceled", "expired"} else None,
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="single service restart",
        plan_snapshot={},
        precheck_result={"passed": True, "snapshot": "creation"},
        verification_policy={},
        idempotency_key=f"idempotency-{status}",
        expires_at=current_time + timedelta(minutes=5),
        output_truncated=False,
        requested_at=current_time,
        updated_at=current_time,
    )


def test_operation_signature_binds_every_executable_field() -> None:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    operation = Operation(
        id="operation-1",
        instance_id="instance-1",
        agent_id="agent-1",
        action_type="docker_restart",
        status="queued",
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="single service restart",
        plan_snapshot={},
        precheck_result={},
        verification_policy={},
        idempotency_key="idempotency-1",
        attempt=1,
        task_nonce="nonce-1",
        signing_key_id="m4-test",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )

    signature = sign_operation(base64.b64encode(raw).decode(), signing_fields(operation, instance))

    key.public_key().verify(
        base64.b64decode(signature), "\n".join(signing_fields(operation, instance)).encode()
    )
    operation.idempotency_key = "tampered"
    try:
        key.public_key().verify(
            base64.b64decode(signature), "\n".join(signing_fields(operation, instance)).encode()
        )
    except Exception:
        pass
    else:
        raise AssertionError("signature accepted a tampered idempotency key")


def test_operation_plan_rejects_arbitrary_target_or_command_fields() -> None:
    with pytest.raises(ValidationError):
        OperationPlanCreate.model_validate(
            {
                "instance_id": "instance-1",
                "action_type": "docker_restart",
                "container_target": "arbitrary-container",
                "command": "docker rm -f arbitrary-container",
            }
        )


def test_unconfirmed_operation_is_not_claimed() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    agent = Agent(id="agent-1")

    result = asyncio.run(claim_operation(agent, session, Settings()))

    assert result.task is None
    session.commit.assert_not_awaited()
    sql = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_concurrent_operation_conflict_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
        restart_enabled=True,
    )
    agent = Agent(id="agent-1", name="agent", hostname="host", last_seen_at=now)
    managed = ManagedService(id="service-1", name="api", criticality="non_critical")

    async def resolve(*_args: object) -> tuple[ServiceInstance, None, None]:
        return instance, None, None

    async def precheck(*_args: object) -> tuple[dict, Agent, ManagedService, None]:
        return {"passed": True}, agent, managed, None

    class NestedTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(operations_module, "resolve_instance", resolve)
    monkeypatch.setattr(operations_module, "run_prechecks", precheck)
    monkeypatch.setattr(operations_module, "now_utc", lambda: now)
    session = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = MagicMock(return_value=NestedTransaction())
    session.flush.side_effect = IntegrityError("insert", {}, RuntimeError("unique conflict"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_operation(OperationPlanCreate(instance_id="instance-1"), session, Settings())
        )

    assert error.value.status_code == 409
    session.rollback.assert_awaited_once()


def test_extracted_restart_plan_preserves_m4_snapshot_and_transition_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
        restart_enabled=True,
    )
    agent = Agent(
        id="agent-1",
        name="agent",
        hostname="host",
        last_seen_at=now,
    )
    managed = ManagedService(
        id="service-1",
        name="api",
        environment="production",
        criticality="non_critical",
    )
    checks = {
        "agent_online": True,
        "docker_instance": True,
        "mapping_valid": True,
        "agent_write_capability": True,
        "control_plane_permission": True,
        "non_critical_service": True,
        "observation_fresh": True,
        "passed": True,
    }

    async def precheck(*_args: object) -> tuple[dict, Agent, ManagedService, None]:
        return checks, agent, managed, None

    class NestedTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    session = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = MagicMock(return_value=NestedTransaction())
    monkeypatch.setattr(operations_module, "run_prechecks", precheck)
    monkeypatch.setattr(operations_module, "now_utc", lambda: now)

    operation = asyncio.run(
        build_restart_plan(
            session,
            instance,
            None,
            None,
            Settings(),
            expires_in_seconds=300,
        )
    )

    assert operation.organization_id == "local"
    assert operation.action_type == "docker_restart"
    assert operation.status == "awaiting_confirmation"
    assert operation.active_key == "instance-1:write"
    assert operation.requested_by == "local-admin"
    assert operation.risk_level == "medium"
    assert operation.precheck_result == checks
    assert operation.source_conversation_turn_id is None
    assert operation.conversation_request_id is None
    assert operation.plan_snapshot["service"]["instance_id"] == instance.id
    assert "conversation_source" not in operation.plan_snapshot
    assert operation.verification_policy == {
        "kind": "fresh_service_observation",
        "requires_healthy": True,
        "required_state": "running",
        "stability_seconds": Settings().operation_verification_window_seconds,
        "timeout_seconds": Settings().operation_verification_timeout_seconds,
    }
    assert operation.expires_at == now + timedelta(seconds=300)
    assert operation.task_signature is None
    assert operation.task_nonce is None
    transitions = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], OperationTransition)
    ]
    assert [(item.from_status, item.to_status) for item in transitions] == [
        (None, "planned"),
        ("planned", "prechecking"),
        ("prechecking", "awaiting_confirmation"),
    ]
    assert transitions[0].reason == "restart plan requested"
    assert transitions[0].details == {"source": "web"}
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "status",
    ["planned", "prechecking", "claimed", "running", "verifying", "succeeded", "failed", "expired"],
)
def test_cancel_rejects_unsafe_states(status: str) -> None:
    session = AsyncMock()
    session.scalar.return_value = make_operation(status)

    with pytest.raises(HTTPException) as error:
        asyncio.run(cancel_operation(f"operation-{status}", session))

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()


def test_cancel_awaiting_operation_is_audited() -> None:
    operation = make_operation("awaiting_confirmation")
    rows = MagicMock()
    rows.all.return_value = []
    session = AsyncMock()
    session.scalar.return_value = operation
    session.scalars.return_value = rows
    session.add = MagicMock()

    result = asyncio.run(cancel_operation(operation.id, session))

    assert result.status == "canceled"
    assert operation.active_key is None
    transition = session.add.call_args.args[0]
    assert isinstance(transition, OperationTransition)
    assert transition.to_status == "canceled"


def test_state_machine_rejects_illegal_transition() -> None:
    operation = make_operation("awaiting_confirmation")
    session = AsyncMock()
    session.add = MagicMock()

    with pytest.raises(ValueError, match="awaiting_confirmation -> succeeded"):
        asyncio.run(transition(session, operation, "succeeded", "control_plane"))

    assert operation.status == "awaiting_confirmation"
    session.add.assert_not_called()


def test_confirmation_precheck_drift_fails_without_overwriting_creation_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = make_operation("awaiting_confirmation")
    creation_snapshot = dict(operation.precheck_result)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    confirmation_checks = {"passed": False, "agent_online": False}

    async def precheck(*_args: object) -> tuple[dict, Agent, ManagedService, None]:
        return confirmation_checks, Agent(id="agent-1"), ManagedService(id="service-1"), None

    rows = MagicMock()
    rows.all.return_value = []
    session = AsyncMock()
    session.scalar.return_value = operation
    session.get.return_value = instance
    session.scalars.return_value = rows
    session.add = MagicMock()
    monkeypatch.setattr(operations_module, "run_prechecks", precheck)

    result = asyncio.run(confirm_operation(operation.id, OperationConfirm(), session, Settings()))

    assert result.status == "failed"
    assert operation.precheck_result == creation_snapshot
    transition = session.add.call_args.args[0]
    assert transition.details["confirmation_precheck"] == confirmation_checks


def test_expired_confirmation_becomes_terminal_without_signing() -> None:
    now = datetime.now(timezone.utc)
    operation = make_operation("awaiting_confirmation", now)
    operation.expires_at = now - timedelta(seconds=1)
    rows = MagicMock()
    rows.all.return_value = []
    session = AsyncMock()
    session.scalar.return_value = operation
    session.scalars.return_value = rows
    session.add = MagicMock()

    result = asyncio.run(confirm_operation(operation.id, OperationConfirm(), session, Settings()))

    assert result.status == "expired"
    assert operation.error_code == "expired"
    session.get.assert_not_awaited()


def test_execution_exit_zero_enters_verification_and_redacts_output() -> None:
    now = datetime.now(timezone.utc)
    operation = Operation(
        id="operation-1",
        instance_id="instance-1",
        agent_id="agent-1",
        action_type="docker_restart",
        status="running",
        active_key="instance-1:write",
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="single service restart",
        plan_snapshot={},
        precheck_result={},
        verification_policy={},
        idempotency_key="idempotency-1",
        expires_at=now + timedelta(minutes=5),
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = operation
    exit_code = 0
    payload = OperationExecutionResult(
        status="completed",
        exit_code=exit_code,
        output="token=must-not-persist\nrestart accepted",
        completed_at=now,
    )

    result = asyncio.run(
        complete_operation("operation-1", payload, Agent(id="agent-1"), session, Settings())
    )

    assert result.status == "verifying"
    assert operation.status == "verifying"
    assert "must-not-persist" not in operation.output
    assert "[REDACTED]" in operation.output


def test_health_verification_not_command_exit_marks_success() -> None:
    now = datetime.now(timezone.utc)
    operation = Operation(
        id="operation-1",
        instance_id="instance-1",
        agent_id="agent-1",
        action_type="docker_restart",
        status="verifying",
        active_key="instance-1:write",
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="single service restart",
        plan_snapshot={},
        precheck_result={},
        verification_policy={},
        verification_result={"first_healthy_at": (now - timedelta(seconds=31)).isoformat()},
        idempotency_key="idempotency-1",
        expires_at=now + timedelta(minutes=5),
        execution_completed_at=now - timedelta(seconds=40),
    )
    result_rows = MagicMock()
    result_rows.all.return_value = [operation]
    session = AsyncMock()
    session.scalars.return_value = result_rows
    session.add = MagicMock()
    session.get.return_value = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    report = AgentReport(
        hostname="test",
        version="test",
        collected_at=now,
        metrics=Metrics(
            cpu_percent=1,
            memory_percent=1,
            memory_used_bytes=1,
            memory_total_bytes=2,
            disks=[],
        ),
        services=[
            ServiceReport(
                kind="docker",
                key="compose:demo:api:1",
                name="api",
                state="running",
                healthy=True,
            )
        ],
    )

    asyncio.run(
        reconcile_operation_verification(
            session,
            Agent(id="agent-1"),
            report,
            now,
            Settings(operation_verification_window_seconds=30),
        )
    )

    assert operation.status == "succeeded"
    assert operation.active_key is None
    assert operation.verification_result["status"] == "passed"


def test_stale_outcomes_keep_verification_independent_from_task_expiry() -> None:
    now = datetime.now(timezone.utc)
    settings = Settings(operation_verification_timeout_seconds=180)

    running = make_operation("running", now)
    running.lease_expires_at = now - timedelta(seconds=1)
    assert stale_operation_outcome(running, settings, now) == (
        "failed",
        "execution_outcome_unknown",
        "Agent stopped reporting after execution started; task was not replayed",
    )

    verifying = make_operation("verifying", now)
    verifying.expires_at = now - timedelta(seconds=1)
    verifying.execution_completed_at = now - timedelta(seconds=30)
    assert stale_operation_outcome(verifying, settings, now) is None

    verifying.execution_completed_at = now - timedelta(seconds=181)
    assert stale_operation_outcome(verifying, settings, now) == (
        "failed",
        "verification_timeout",
        "health verification timed out",
    )

    queued = make_operation("queued", now)
    queued.expires_at = now - timedelta(seconds=1)
    assert stale_operation_outcome(queued, settings, now) == (
        "expired",
        "expired",
        "operation task expired",
    )


def test_recover_stale_operations_covers_running_verifying_and_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    settings = Settings(operation_verification_timeout_seconds=180)
    running = make_operation("running", now)
    running.lease_expires_at = now - timedelta(seconds=1)
    verifying = make_operation("verifying", now)
    verifying.execution_completed_at = now - timedelta(seconds=181)
    queued = make_operation("queued", now)
    queued.expires_at = now - timedelta(seconds=1)
    rows = MagicMock()
    rows.all.return_value = [running, verifying, queued]
    session = AsyncMock()
    session.scalars.return_value = rows
    session.add = MagicMock()

    class SessionContext:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(operations_module, "session_factory", SessionContext)

    changed = asyncio.run(recover_stale_operations(settings, current_time=now))

    assert changed == 3
    assert (running.status, running.error_code) == ("failed", "execution_outcome_unknown")
    assert (verifying.status, verifying.error_code) == ("failed", "verification_timeout")
    assert (queued.status, queued.error_code) == ("expired", "expired")
    session.commit.assert_awaited_once()


def test_running_lease_includes_result_upload_grace() -> None:
    now = datetime.now(timezone.utc)
    operation = make_operation("claimed", now)
    session = AsyncMock()
    session.scalar.return_value = operation
    session.add = MagicMock()
    settings = Settings(
        operation_execution_timeout_seconds=30,
        operation_execution_result_grace_seconds=15,
    )

    result = asyncio.run(
        operations_module.start_operation(operation.id, Agent(id="agent-1"), session, settings)
    )

    assert result.status == "running"
    assert operation.lease_expires_at == operation.started_at + timedelta(seconds=45)
