import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.conversation_operations import conversation_operation_timeline
from app.models import (
    Agent,
    AlertEvent,
    ConversationSession,
    ConversationTurn,
    DiagnosticRun,
    ManagedService,
    Operation,
    OperationTransition,
    ServiceInstance,
)

POSTGRES_URL = os.getenv("M5_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M5_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_operation_timeline_scope_projection_and_zero_side_effect() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        local_agent = Agent(
            id=str(uuid4()),
            organization_id="local",
            credential_hash=uuid4().hex * 2,
            name="M5.3.3 timeline agent",
            hostname=f"m533-{uuid4()}.invalid",
            machine_id=f"m533-{uuid4()}",
            os="linux",
            arch="amd64",
            version="test",
            capabilities=[],
            last_seen_at=now,
        )
        other_agent = Agent(
            id=str(uuid4()),
            organization_id="other-org",
            credential_hash=uuid4().hex * 2,
            name="Other organization timeline agent",
            hostname=f"m533-other-{uuid4()}.invalid",
            machine_id=f"m533-other-{uuid4()}",
            os="linux",
            arch="amd64",
            version="test",
            capabilities=[],
            last_seen_at=now,
        )
        service = ManagedService(
            id=str(uuid4()),
            organization_id="local",
            name="M5.3.3 timeline service",
            environment="test",
            criticality="non_critical",
        )
        instance = ServiceInstance(
            id=str(uuid4()),
            service_id=service.id,
            agent_id=local_agent.id,
            service_kind="docker",
            service_key=f"compose:m533-{uuid4().hex}:api:1",
        )
        current_event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=local_agent.id,
            fingerprint=uuid4().hex * 2,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="Current timeline event",
            severity="warning",
            status="firing",
            observation_count=1,
            first_observed_at=now,
            last_observed_at=now,
        )
        other_event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=local_agent.id,
            fingerprint=uuid4().hex * 2,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="Different local event",
            severity="warning",
            status="resolved",
            observation_count=1,
            first_observed_at=now,
            last_observed_at=now,
            resolved_at=now,
        )
        cross_org_event = AlertEvent(
            id=str(uuid4()),
            organization_id="other-org",
            agent_id=other_agent.id,
            fingerprint=uuid4().hex * 2,
            source="agent",
            title="Cross organization event",
            severity="critical",
            status="firing",
            observation_count=1,
            first_observed_at=now,
            last_observed_at=now,
        )
        diagnostic = DiagnosticRun(
            id=str(uuid4()),
            organization_id="local",
            event_id=current_event.id,
            status="completed",
            trigger="manual",
            provider="deterministic",
            result={},
            created_at=now,
            completed_at=now,
        )
        conversation = ConversationSession(
            id=str(uuid4()),
            organization_id="local",
            scope_type="event",
            event_id=current_event.id,
            created_by="integration-test",
        )
        turn = ConversationTurn(
            id=str(uuid4()),
            organization_id="local",
            session_id=conversation.id,
            client_request_id=str(uuid4()),
            question="What happened?",
            status="completed",
            provider="deterministic",
            answer={
                "summary": "bounded",
                "facts": [],
                "inferences": [],
                "recommendations": [],
                "missing_evidence": [],
            },
            context_manifest={},
            completed_at=now,
        )

        def operation(
            *,
            source_event_id: str | None = None,
            source_diagnostic_id: str | None = None,
            source_conversation_turn_id: str | None = None,
            requested_at: datetime,
        ) -> Operation:
            return Operation(
                id=str(uuid4()),
                organization_id="local",
                instance_id=instance.id,
                agent_id=local_agent.id,
                source_event_id=source_event_id,
                source_diagnostic_id=source_diagnostic_id,
                source_conversation_turn_id=source_conversation_turn_id,
                action_type="docker_restart",
                status="succeeded",
                active_key=None,
                requested_by="local-admin",
                risk_level="medium",
                impact_summary="bounded timeline operation",
                plan_snapshot={"secret_path": "/not/returned"},
                precheck_result={"passed": True},
                verification_policy={},
                verification_result={
                    "status": "passed",
                    "target_digest": "not-returned",
                },
                idempotency_key=f"m533_{uuid4().hex}",
                expires_at=requested_at + timedelta(minutes=5),
                requested_at=requested_at,
                completed_at=requested_at + timedelta(seconds=10),
                output="not returned",
            )

        event_operation = operation(
            source_event_id=current_event.id,
            requested_at=now + timedelta(seconds=2),
        )
        diagnostic_operation = operation(
            source_diagnostic_id=diagnostic.id,
            requested_at=now + timedelta(seconds=1),
        )
        conversation_operation = operation(
            source_conversation_turn_id=turn.id,
            requested_at=now + timedelta(milliseconds=500),
        )
        older_event_operations = [
            operation(
                source_event_id=current_event.id,
                requested_at=now - timedelta(seconds=index),
            )
            for index in range(1, 19)
        ]
        unrelated_operation = operation(
            source_event_id=other_event.id,
            requested_at=now,
        )
        transition = OperationTransition(
            id=str(uuid4()),
            operation_id=event_operation.id,
            from_status="verifying",
            to_status="succeeded",
            actor_type="control_plane",
            actor_id="not-returned",
            reason="fresh health verification passed",
            details={"target": "not-returned"},
            created_at=now + timedelta(seconds=3),
        )

        try:
            async with factory() as session:
                session.add_all([local_agent, other_agent, service])
                await session.commit()
                session.add(instance)
                await session.commit()
                session.add_all([current_event, other_event, cross_org_event])
                await session.commit()
                session.add_all([diagnostic, conversation])
                await session.commit()
                session.add(turn)
                await session.commit()
                session.add_all([
                    event_operation,
                    diagnostic_operation,
                    conversation_operation,
                    *older_event_operations,
                    unrelated_operation,
                ])
                await session.commit()
                session.add(transition)
                await session.commit()

                operations_before = await session.scalar(
                    select(func.count()).select_from(Operation)
                )
                transitions_before = await session.scalar(
                    select(func.count()).select_from(OperationTransition)
                )
                result = await conversation_operation_timeline(
                    current_event.id,
                    session,
                    Settings(conversation_operation_timeline_enabled=True),
                )
                assert len(result.operations) == 20
                assert [item.id for item in result.operations[:3]] == [
                    event_operation.id,
                    diagnostic_operation.id,
                    conversation_operation.id,
                ]
                assert older_event_operations[-1].id not in {
                    item.id for item in result.operations
                }
                assert unrelated_operation.id not in {
                    item.id for item in result.operations
                }
                assert result.operations[0].verification_status == "passed"
                assert result.operations[0].transitions[0].to_status == "succeeded"
                assert "not-returned" not in str(result.model_dump(mode="json"))
                assert (
                    await session.scalar(select(func.count()).select_from(Operation))
                    == operations_before
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(OperationTransition)
                    )
                    == transitions_before
                )

                with pytest.raises(HTTPException) as cross_org:
                    await conversation_operation_timeline(
                        cross_org_event.id,
                        session,
                        Settings(conversation_operation_timeline_enabled=True),
                    )
                assert cross_org.value.status_code == 404
        finally:
            async with factory() as session:
                await session.execute(
                    delete(Operation).where(
                        Operation.id.in_(
                            [
                                event_operation.id,
                                diagnostic_operation.id,
                                conversation_operation.id,
                                *[
                                    operation.id
                                    for operation in older_event_operations
                                ],
                                unrelated_operation.id,
                            ]
                        )
                    )
                )
                await session.execute(
                    delete(ConversationSession).where(
                        ConversationSession.id == conversation.id
                    )
                )
                await session.execute(
                    delete(DiagnosticRun).where(DiagnosticRun.id == diagnostic.id)
                )
                await session.execute(
                    delete(AlertEvent).where(
                        AlertEvent.id.in_(
                            [current_event.id, other_event.id, cross_org_event.id]
                        )
                    )
                )
                await session.execute(
                    delete(ServiceInstance).where(ServiceInstance.id == instance.id)
                )
                await session.execute(
                    delete(ManagedService).where(ManagedService.id == service.id)
                )
                await session.execute(
                    delete(Agent).where(
                        Agent.id.in_([local_agent.id, other_agent.id])
                    )
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
