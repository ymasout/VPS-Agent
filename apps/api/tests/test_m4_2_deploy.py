import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import app.api as api_module
import app.operations as operations_module
from app.api import report_agent
from app.config import Settings
from app.image_refs import normalize_repository, parse_digest_reference
from app.models import (
    Agent,
    AgentDeploymentCandidate,
    AgentOperationCapability,
    ManagedService,
    Operation,
    ServiceInstance,
    ServiceStatus,
)
from app.operations import (
    cancel_operation,
    claim_operation,
    complete_operation,
    confirm_operation,
    create_deployment_operation,
    create_deployment_plan,
    deployment_signing_fields,
    reconcile_operation_verification,
    start_operation,
)
from app.schemas import (
    AgentReport,
    DeploymentCandidateReport,
    DeploymentPlanCreate,
    Metrics,
    OperationConfirm,
    OperationExecutionResult,
    ServiceReport,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("ubuntu:24.04", "docker.io/library/ubuntu"),
        ("library/ubuntu", "docker.io/library/ubuntu"),
        ("index.docker.io/library/nginx", "docker.io/library/nginx"),
        ("ghcr.io/Org/App:v1", "ghcr.io/org/app"),
        ("localhost:5000/team/api:tag", "localhost:5000/team/api"),
    ],
)
def test_repository_normalization_matches_agent_vectors(reference: str, expected: str) -> None:
    assert normalize_repository(reference) == expected


def test_digest_reference_requires_one_canonical_sha256() -> None:
    repository, canonical = parse_digest_reference(f"ghcr.io/org/app@{DIGEST_A}")
    assert repository == "ghcr.io/org/app"
    assert canonical == f"ghcr.io/org/app@{DIGEST_A}"
    for invalid in (
        "ghcr.io/org/app:latest",
        "ghcr.io/org/app@sha256:ABC",
        "https://ghcr.io/org/app@" + DIGEST_A,
    ):
        with pytest.raises(ValueError):
            parse_digest_reference(invalid)


def test_candidate_schema_preserves_read_only_eligibility_invariants() -> None:
    eligible = DeploymentCandidateReport(
        service_kind="docker",
        service_key="compose:demo:api:1",
        repository="ghcr.io/org/app",
        current_digest=f"ghcr.io/org/app@{DIGEST_A}",
        eligible=True,
    )
    assert eligible.reason_code is None
    with pytest.raises(ValidationError):
        DeploymentCandidateReport(
            service_kind="docker",
            service_key="compose:demo:api:1",
            eligible=False,
        )
    with pytest.raises(ValidationError):
        DeploymentCandidateReport(
            service_kind="docker",
            service_key="compose:demo:api:1",
            repository="ghcr.io/org/app",
            current_digest=f"ghcr.io/other/app@{DIGEST_A}",
            eligible=True,
        )


def test_report_replaces_candidates_using_server_receipt_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_at = datetime(2026, 7, 22, 1, 2, tzinfo=timezone.utc)
    collected_at = received_at - timedelta(minutes=5)
    agent = Agent(
        id="agent-1",
        credential_hash="hash",
        name="canary",
        hostname="host",
        machine_id="machine-1",
        os="Linux",
        arch="amd64",
        version="0.4.0",
        capabilities=[],
        last_seen_at=collected_at,
    )
    payload = AgentReport(
        hostname="host",
        version="0.4.0",
        collected_at=collected_at,
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
                name="demo-api-1",
                state="running",
                healthy=True,
            )
        ],
        deployment_candidates=[
            DeploymentCandidateReport(
                service_kind="docker",
                service_key="compose:demo:api:1",
                repository="ghcr.io/org/app",
                current_digest=f"ghcr.io/org/app@{DIGEST_A}",
                eligible=True,
            )
        ],
    )
    session = AsyncMock()
    session.scalar.return_value = agent
    rows = MagicMock()
    rows.all.return_value = []
    session.scalars.return_value = rows
    session.add = MagicMock()
    session.add_all = MagicMock()
    monkeypatch.setattr(api_module, "now_utc", lambda: received_at)
    monkeypatch.setattr(api_module, "evaluate_agent_availability", AsyncMock(return_value=[]))
    monkeypatch.setattr(api_module, "evaluate_service_alerts", AsyncMock(return_value=[]))
    monkeypatch.setattr(api_module, "reconcile_service_instance_keys", AsyncMock())

    asyncio.run(report_agent(payload, BackgroundTasks(), agent, session, Settings()))

    inserted = [
        item
        for call in session.add_all.call_args_list
        for item in call.args[0]
        if isinstance(item, AgentDeploymentCandidate)
    ]
    assert len(inserted) == 1
    assert inserted[0].observed_at == received_at
    assert inserted[0].observed_at != collected_at


def deploy_operation(status: str = "planned") -> Operation:
    now = datetime.now(timezone.utc)
    return Operation(
        id="deploy-plan-1",
        instance_id="instance-1",
        agent_id="agent-1",
        action_type="docker_compose_deploy",
        status=status,
        requested_by="local-admin",
        risk_level="medium",
        impact_summary="plan only",
        plan_snapshot={"permanently_non_executable": True},
        precheck_result={"passed": True},
        verification_policy={"execution_available": False},
        idempotency_key="plan-only-1",
        expires_at=now + timedelta(minutes=15),
    )


def test_create_deployment_plan_freezes_non_executable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    agent = Agent(id="agent-1", name="canary", hostname="host", last_seen_at=now)
    service = ManagedService(id="service-1", name="api", criticality="non_critical")
    candidate = AgentDeploymentCandidate(
        agent_id="agent-1",
        service_kind="docker",
        service_key=instance.service_key,
        repository="ghcr.io/org/app",
        current_digest=f"ghcr.io/org/app@{DIGEST_A}",
        eligible=True,
        observed_at=now,
    )
    observation = ServiceStatus(
        agent_id="agent-1",
        kind="docker",
        service_key=instance.service_key,
        name="demo-api-1",
        state="running",
        healthy=True,
        observed_at=now,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.get.side_effect = [instance, agent, service]
    session.scalar.side_effect = [candidate, observation]

    async def return_model(_session: object, operation: Operation) -> Operation:
        return operation

    monkeypatch.setattr(operations_module, "now_utc", lambda: now)
    monkeypatch.setattr(operations_module, "operation_view", return_model)

    plan = asyncio.run(
        create_deployment_plan(
            DeploymentPlanCreate(
                instance_id=instance.id,
                target_digest=f"ghcr.io/org/app@{DIGEST_B}",
            ),
            session,
            Settings(),
        )
    )

    assert plan.status == "planned"
    assert plan.action_type == "docker_compose_deploy"
    assert plan.active_key is None
    assert plan.plan_snapshot["plan_version"] == "m4.2a-plan-only-v1"
    assert plan.plan_snapshot["permanently_non_executable"] is True
    assert plan.plan_snapshot["target_digest"] == f"ghcr.io/org/app@{DIGEST_B}"
    assert plan.verification_policy["execution_available"] is False
    assert plan.task_signature is None and plan.task_nonce is None


def test_deployment_plan_rejects_cross_repository_target() -> None:
    now = datetime.now(timezone.utc)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    session = AsyncMock()
    session.get.side_effect = [
        instance,
        Agent(id="agent-1", last_seen_at=now),
        ManagedService(id="service-1", criticality="non_critical"),
    ]
    candidate = AgentDeploymentCandidate(
        agent_id="agent-1",
        service_kind="docker",
        service_key=instance.service_key,
        repository="ghcr.io/org/app",
        current_digest=f"ghcr.io/org/app@{DIGEST_A}",
        eligible=True,
        observed_at=now,
    )
    observation = ServiceStatus(
        agent_id="agent-1",
        kind="docker",
        service_key=instance.service_key,
        name="demo-api-1",
        state="running",
        healthy=True,
        observed_at=now,
    )
    session.scalar.side_effect = [candidate, observation]
    with pytest.raises(HTTPException, match="current repository") as error:
        asyncio.run(
            create_deployment_plan(
                DeploymentPlanCreate(
                    instance_id=instance.id,
                    target_digest=f"ghcr.io/org/other@{DIGEST_B}",
                ),
                session,
                Settings(),
            )
        )
    assert error.value.status_code == 409


def test_all_existing_execution_endpoints_reject_deploy_action() -> None:
    agent = Agent(id="agent-1")
    settings = Settings()
    result = OperationExecutionResult(
        status="failed",
        exit_code=-1,
        completed_at=datetime.now(timezone.utc),
    )
    calls = (
        lambda session: confirm_operation("deploy-plan-1", OperationConfirm(), session, settings),
        lambda session: cancel_operation("deploy-plan-1", session),
        lambda session: start_operation("deploy-plan-1", agent, session, settings),
        lambda session: complete_operation("deploy-plan-1", result, agent, session, settings),
    )
    for call in calls:
        session = AsyncMock()
        session.scalar.return_value = deploy_operation("claimed")
        with pytest.raises(HTTPException, match="plan-only") as error:
            asyncio.run(call(session))
        assert error.value.status_code == 409
        session.commit.assert_not_awaited()


def test_agent_claim_query_explicitly_filters_supported_actions() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    claim = asyncio.run(claim_operation(Agent(id="agent-1"), session, Settings()))
    assert claim.task is None
    sql = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "operations.action_type" in sql


def executable_deploy_operation(status: str = "awaiting_confirmation") -> Operation:
    operation = deploy_operation(status)
    operation.plan_snapshot = {
        "plan_version": "m4.2b-executable-v1",
        "permanently_non_executable": False,
    }
    operation.active_key = "instance-1:write"
    operation.current_digest = f"ghcr.io/org/app@{DIGEST_A}"
    operation.target_digest = f"ghcr.io/org/app@{DIGEST_B}"
    return operation


def signed_executable_deploy_operation(status: str = "queued") -> Operation:
    operation = executable_deploy_operation(status)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    operation.issued_at = now
    operation.task_nonce = "nonce-v2"
    operation.signing_key_id = "key-1"
    operation.task_signature = "signed-v2"
    operation.attempt = 1
    return operation


def test_v2_signature_binds_both_digests() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    operation = executable_deploy_operation()
    operation.issued_at = now
    operation.task_nonce = "nonce"
    operation.signing_key_id = "key-1"
    fields = deployment_signing_fields(
        operation,
        ServiceInstance(service_kind="docker", service_key="compose:demo:api:1"),
    )
    assert fields[:8] == [
        "v2",
        operation.id,
        "docker_compose_deploy",
        "agent-1",
        "docker",
        "compose:demo:api:1",
        operation.current_digest,
        operation.target_digest,
    ]


def test_agent_claim_returns_strict_v2_deployment_task() -> None:
    operation = signed_executable_deploy_operation()
    session = AsyncMock()
    session.scalar.side_effect = [
        operation,
        AgentOperationCapability(
            agent_id="agent-1",
            action_type="docker_compose_deploy",
            service_kind="docker",
            service_key="compose:demo:api:1",
        ),
    ]
    session.get.return_value = ServiceInstance(
        id="instance-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    session.add = MagicMock()

    claim = asyncio.run(claim_operation(Agent(id="agent-1"), session, Settings()))

    assert claim.task is not None
    assert claim.task.version == "v2"
    assert claim.task.current_digest == operation.current_digest
    assert claim.task.target_digest == operation.target_digest
    assert operation.status == "claimed"


def test_agent_claim_fails_closed_for_queued_historical_plan() -> None:
    operation = deploy_operation("queued")
    session = AsyncMock()
    session.scalar.return_value = operation
    session.get.return_value = ServiceInstance(
        id="instance-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    session.add = MagicMock()

    claim = asyncio.run(claim_operation(Agent(id="agent-1"), session, Settings()))

    assert claim.task is None
    assert operation.status == "failed"
    assert operation.error_code == "invalid_plan"


def test_deployment_confirmation_rejects_changed_current_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = executable_deploy_operation()
    instance = ServiceInstance(
        id="instance-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    session = AsyncMock()
    session.scalar.return_value = operation
    session.get.return_value = instance
    session.add = MagicMock()
    monkeypatch.setattr(
        operations_module,
        "run_deploy_prechecks",
        AsyncMock(
            return_value=(
                {"passed": False, "current_digest_unchanged": False},
                Agent(id="agent-1"),
                ManagedService(id="service-1"),
                None,
                AgentDeploymentCandidate(
                    current_digest=f"ghcr.io/org/app@{DIGEST_B}",
                    eligible=True,
                ),
            )
        ),
    )

    async def return_model(_session: object, current: Operation) -> Operation:
        return current

    monkeypatch.setattr(operations_module, "operation_view", return_model)

    result = asyncio.run(
        confirm_operation(
            operation.id,
            OperationConfirm(),
            session,
            Settings(),
        )
    )

    assert result.status == "failed"
    assert result.error_code == "precheck_failed"


def test_create_executable_deployment_is_new_locked_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
        deploy_enabled=True,
    )
    agent = Agent(id="agent-1", name="canary", hostname="host", last_seen_at=now)
    service = ManagedService(id="service-1", name="api", criticality="non_critical")
    candidate = AgentDeploymentCandidate(
        agent_id="agent-1",
        service_kind="docker",
        service_key=instance.service_key,
        repository="ghcr.io/org/app",
        current_digest=f"ghcr.io/org/app@{DIGEST_A}",
        eligible=True,
        observed_at=now,
    )
    observation = ServiceStatus(
        agent_id="agent-1",
        kind="docker",
        service_key=instance.service_key,
        name="demo-api-1",
        state="running",
        healthy=True,
        observed_at=now,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = instance

    class Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    session.begin_nested = MagicMock(return_value=Transaction())
    monkeypatch.setattr(operations_module, "now_utc", lambda: now)
    monkeypatch.setattr(
        operations_module,
        "run_deploy_prechecks",
        AsyncMock(
            return_value=(
                {"passed": True},
                agent,
                service,
                observation,
                candidate,
            )
        ),
    )

    async def return_model(_session: object, operation: Operation) -> Operation:
        return operation

    monkeypatch.setattr(operations_module, "operation_view", return_model)
    result = asyncio.run(
        create_deployment_operation(
            DeploymentPlanCreate(
                instance_id=instance.id,
                target_digest=f"ghcr.io/org/app@{DIGEST_B}",
            ),
            session,
            Settings(),
        )
    )
    assert result.status == "awaiting_confirmation"
    assert result.active_key == "instance-1:write"
    assert result.plan_snapshot["plan_version"] == "m4.2b-executable-v1"
    assert result.current_digest == f"ghcr.io/org/app@{DIGEST_A}"
    assert result.target_digest == f"ghcr.io/org/app@{DIGEST_B}"


def test_deploy_verification_requires_digest_and_health_in_same_report() -> None:
    now = datetime.now(timezone.utc)
    operation = executable_deploy_operation("verifying")
    operation.execution_completed_at = now - timedelta(seconds=1)
    operation.verification_result = {"status": "waiting_for_fresh_observation"}
    rows = MagicMock()
    rows.all.return_value = [operation]
    session = AsyncMock()
    session.scalars.return_value = rows
    session.get.return_value = ServiceInstance(
        id="instance-1",
        service_kind="docker",
        service_key="compose:demo:api:1",
    )
    session.add = MagicMock()
    report = AgentReport(
        hostname="host",
        version="0.4.2-dev",
        collected_at=now,
        metrics=Metrics(
            cpu_percent=1,
            memory_percent=1,
            memory_used_bytes=1,
            memory_total_bytes=2,
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
        deployment_candidates=[
            DeploymentCandidateReport(
                service_kind="docker",
                service_key="compose:demo:api:1",
                repository="ghcr.io/org/app",
                current_digest=f"ghcr.io/org/app@{DIGEST_B}",
                eligible=True,
            )
        ],
    )
    asyncio.run(
        reconcile_operation_verification(
            session,
            Agent(id="agent-1"),
            report,
            now,
            Settings(operation_verification_window_seconds=0),
        )
    )
    assert operation.status == "succeeded"
    assert operation.verification_result["observed_digest"] == operation.target_digest

    operation.status = "verifying"
    operation.verification_result = {"status": "waiting_for_fresh_observation"}
    report.deployment_candidates[0].current_digest = f"ghcr.io/org/app@{DIGEST_A}"
    asyncio.run(
        reconcile_operation_verification(
            session,
            Agent(id="agent-1"),
            report,
            now + timedelta(seconds=1),
            Settings(operation_verification_window_seconds=0),
        )
    )
    assert operation.status == "verifying"
    assert operation.verification_result["observed_digest"] == f"ghcr.io/org/app@{DIGEST_A}"
