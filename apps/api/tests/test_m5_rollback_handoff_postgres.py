import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.conversation_operations import (
    create_conversation_restart_plan,
    create_conversation_rollback_plan,
)
from app.models import (
    Agent,
    AgentDeploymentCandidate,
    AgentOperationCapability,
    AlertEvent,
    ConversationSession,
    ConversationTurn,
    ManagedService,
    Operation,
    ServiceInstance,
    ServiceStatus,
)
from app.schemas import ConversationRestartPlanCreate, ConversationRollbackPlanCreate

POSTGRES_URL = os.getenv("M5_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M5_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)

DIGEST_A = "ghcr.io/example/app@sha256:" + "a" * 64
DIGEST_B = "ghcr.io/example/app@sha256:" + "b" * 64


def test_conversation_rollback_derivation_idempotency_and_mutex() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        suffix = uuid4().hex
        agent = Agent(
            id=str(uuid4()),
            organization_id="local",
            credential_hash=uuid4().hex * 2,
            name="M5.3.2 integration agent",
            hostname=f"m5-rollback-{suffix}.invalid",
            machine_id=f"m5-rollback-{uuid4()}",
            os="linux",
            arch="amd64",
            version="test",
            capabilities=[],
            last_seen_at=now,
        )
        service = ManagedService(
            id=str(uuid4()),
            organization_id="local",
            name="M5.3.2 integration service",
            environment="test",
            criticality="non_critical",
        )
        instance = ServiceInstance(
            id=str(uuid4()),
            service_id=service.id,
            agent_id=agent.id,
            service_kind="docker",
            service_key=f"compose:m5-rollback-{suffix}:api:1",
            restart_enabled=True,
            deploy_enabled=True,
        )
        event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=agent.id,
            fingerprint=uuid4().hex * 2,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="M5.3.2 integration event",
            severity="warning",
            status="firing",
            observation_count=2,
            first_observed_at=now - timedelta(seconds=45),
            last_observed_at=now,
        )
        other_event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=agent.id,
            fingerprint=uuid4().hex * 2,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="Different event on the same instance",
            severity="warning",
            status="resolved",
            observation_count=2,
            first_observed_at=now - timedelta(seconds=45),
            last_observed_at=now,
            resolved_at=now,
        )
        conversation = ConversationSession(
            id=str(uuid4()),
            organization_id="local",
            scope_type="event",
            event_id=event.id,
            created_by="integration-test",
        )
        turn = ConversationTurn(
            id=str(uuid4()),
            organization_id="local",
            session_id=conversation.id,
            client_request_id=str(uuid4()),
            question="Should this be rolled back?",
            status="completed",
            provider="deterministic",
            answer={
                "summary": "bounded",
                "facts": [],
                "inferences": [],
                "recommendations": [],
                "missing_evidence": [],
            },
            context_manifest={"scope_type": "event"},
            completed_at=now,
        )
        status_row = ServiceStatus(
            id=str(uuid4()),
            agent_id=agent.id,
            kind="docker",
            service_key=instance.service_key,
            name="api",
            state="running",
            detail="unhealthy",
            healthy=False,
            observed_at=now,
        )
        capabilities = [
            AgentOperationCapability(
                id=str(uuid4()),
                agent_id=agent.id,
                action_type=action_type,
                service_kind="docker",
                service_key=instance.service_key,
                observed_at=now,
            )
            for action_type in ("docker_restart", "docker_compose_deploy")
        ]
        candidate = AgentDeploymentCandidate(
            id=str(uuid4()),
            agent_id=agent.id,
            service_kind="docker",
            service_key=instance.service_key,
            repository="ghcr.io/example/app",
            current_digest=DIGEST_B,
            eligible=True,
            observed_at=now,
        )
        failed_deploy = Operation(
            id=str(uuid4()),
            organization_id="local",
            instance_id=instance.id,
            agent_id=agent.id,
            source_event_id=event.id,
            action_type="docker_compose_deploy",
            status="failed",
            active_key=None,
            requested_by="local-admin",
            risk_level="high",
            impact_summary="failed deploy",
            plan_snapshot={"plan_version": "m4.2b-executable-v1"},
            precheck_result={"passed": True},
            verification_policy={},
            idempotency_key=f"deploy_{uuid4().hex}",
            current_digest=DIGEST_A,
            target_digest=DIGEST_B,
            expires_at=now + timedelta(minutes=5),
            started_at=now - timedelta(seconds=60),
            execution_completed_at=now - timedelta(seconds=30),
            completed_at=now - timedelta(seconds=5),
            error_code="verification_timeout",
        )
        other_event_failed_deploy = Operation(
            id=str(uuid4()),
            organization_id="local",
            instance_id=instance.id,
            agent_id=agent.id,
            source_event_id=other_event.id,
            action_type="docker_compose_deploy",
            status="failed",
            active_key=None,
            requested_by="local-admin",
            risk_level="high",
            impact_summary="different event failed deploy",
            plan_snapshot={"plan_version": "m4.2b-executable-v1"},
            precheck_result={"passed": True},
            verification_policy={},
            idempotency_key=f"deploy_{uuid4().hex}",
            current_digest=DIGEST_A,
            target_digest=DIGEST_B,
            expires_at=now + timedelta(minutes=5),
            started_at=now - timedelta(seconds=60),
            execution_completed_at=now - timedelta(seconds=30),
            completed_at=now - timedelta(seconds=5),
            error_code="verification_timeout",
        )
        agent_id = agent.id
        service_id = service.id
        instance_id = instance.id
        event_id = event.id
        other_event_id = other_event.id
        conversation_id = conversation.id
        turn_id = turn.id
        failed_deploy_id = failed_deploy.id
        other_event_failed_deploy_id = other_event_failed_deploy.id
        created_operation_id: str | None = None
        try:
            async with factory() as session:
                session.add_all([agent, service])
                await session.commit()
                session.add(instance)
                await session.commit()
                session.add_all([event, other_event])
                await session.commit()
                session.add(conversation)
                await session.commit()
                session.add(turn)
                await session.commit()
                session.add_all([status_row, candidate, *capabilities])
                await session.commit()
                session.add_all([failed_deploy, other_event_failed_deploy])
                await session.commit()

                request_id = str(uuid4())
                settings = Settings(
                    conversation_operation_handoff_enabled=True,
                    operation_observation_max_age_seconds=120,
                )
                created = await create_conversation_rollback_plan(
                    event.id,
                    turn.id,
                    ConversationRollbackPlanCreate(
                        client_request_id=request_id,
                        expires_in_seconds=300,
                    ),
                    session,
                    settings,
                )
                created_operation_id = created.id
                assert created.status == "awaiting_confirmation"
                assert created.rollback_of == failed_deploy_id
                assert created.current_digest == DIGEST_B
                assert created.target_digest == DIGEST_A
                assert created.source_event_id == event.id
                assert created.source_conversation_turn_id == turn.id
                assert created.plan_snapshot["conversation_source"]["handoff_kind"] == (
                    "explicit_user_rollback_plan"
                )
                assert turn.question not in str(created.plan_snapshot)
                persisted_created = await session.get(Operation, created.id)
                assert persisted_created is not None
                assert persisted_created.task_signature is None
                assert persisted_created.task_nonce is None

                repeated = await create_conversation_rollback_plan(
                    event.id,
                    turn.id,
                    ConversationRollbackPlanCreate(
                        client_request_id=request_id,
                        expires_in_seconds=300,
                    ),
                    session,
                    settings,
                )
                assert repeated.id == created.id

                with pytest.raises(HTTPException) as conflict:
                    await create_conversation_restart_plan(
                        event.id,
                        turn.id,
                        ConversationRestartPlanCreate(
                            client_request_id=str(uuid4()),
                            expires_in_seconds=300,
                        ),
                        session,
                        settings,
                    )
                assert conflict.value.status_code == 409
                assert conflict.value.detail == (
                    "another write operation is active for this service"
                )

                await session.execute(
                    delete(ConversationTurn).where(ConversationTurn.id == turn_id)
                )
                await session.commit()
                persisted = await session.get(Operation, created.id)
                assert persisted is not None
                assert persisted.source_conversation_turn_id is None
                assert persisted.plan_snapshot["conversation_source"]["turn_id"] == turn_id
        finally:
            async with factory() as session:
                await session.execute(
                    delete(Operation).where(
                        Operation.id.in_(
                            [
                                item
                                for item in (
                                    created_operation_id,
                                    failed_deploy_id,
                                    other_event_failed_deploy_id,
                                )
                                if item
                            ]
                        )
                    )
                )
                await session.execute(
                    delete(ConversationSession).where(
                        ConversationSession.id == conversation_id
                    )
                )
                await session.execute(delete(AlertEvent).where(AlertEvent.id == event_id))
                await session.execute(
                    delete(AlertEvent).where(AlertEvent.id == other_event_id)
                )
                await session.execute(
                    delete(AgentOperationCapability).where(
                        AgentOperationCapability.agent_id == agent_id
                    )
                )
                await session.execute(
                    delete(AgentDeploymentCandidate).where(
                        AgentDeploymentCandidate.agent_id == agent_id
                    )
                )
                await session.execute(
                    delete(ServiceStatus).where(ServiceStatus.agent_id == agent_id)
                )
                await session.execute(
                    delete(ServiceInstance).where(ServiceInstance.id == instance_id)
                )
                await session.execute(
                    delete(ManagedService).where(ManagedService.id == service_id)
                )
                await session.execute(delete(Agent).where(Agent.id == agent_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
