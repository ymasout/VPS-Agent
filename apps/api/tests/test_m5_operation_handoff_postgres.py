import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Agent,
    AlertEvent,
    ConversationSession,
    ConversationTurn,
    ManagedService,
    Operation,
    ServiceInstance,
)

POSTGRES_URL = os.getenv("M5_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M5_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_conversation_operation_source_fk_and_request_uniqueness() -> None:
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
            name="M5.3 integration agent",
            hostname=f"m5-handoff-{suffix}.invalid",
            machine_id=f"m5-handoff-{uuid4()}",
            os="linux",
            arch="amd64",
            version="test",
            capabilities=[],
            last_seen_at=now,
        )
        service = ManagedService(
            id=str(uuid4()),
            organization_id="local",
            name="M5.3 integration service",
            environment="test",
            criticality="non_critical",
        )
        instance = ServiceInstance(
            id=str(uuid4()),
            service_id=service.id,
            agent_id=agent.id,
            service_kind="docker",
            service_key=f"compose:m5-{suffix}:api:1",
            restart_enabled=True,
        )
        event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=agent.id,
            fingerprint=uuid4().hex * 2,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="M5.3 integration event",
            severity="warning",
            status="firing",
            observation_count=2,
            first_observed_at=now,
            last_observed_at=now,
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
            question="What is confirmed?",
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
        request_id = str(uuid4())
        tombstone = {
            "turn_id": turn.id,
            "answer_sha256": "a" * 64,
            "context_manifest_sha256": "b" * 64,
            "handoff_kind": "explicit_user_restart_plan",
        }
        operation = Operation(
            id=str(uuid4()),
            organization_id="local",
            instance_id=instance.id,
            agent_id=agent.id,
            source_event_id=event.id,
            source_conversation_turn_id=turn.id,
            conversation_request_id=request_id,
            action_type="docker_restart",
            status="awaiting_confirmation",
            active_key=f"{instance.id}:write",
            requested_by="local-admin",
            risk_level="medium",
            impact_summary="restart",
            plan_snapshot={"conversation_source": tombstone},
            precheck_result={"passed": True},
            verification_policy={},
            idempotency_key=f"op_{uuid4().hex}",
            expires_at=now + timedelta(minutes=5),
        )
        operation_id = operation.id
        turn_id = turn.id
        agent_id = agent.id
        service_id = service.id
        try:
            async with factory() as session:
                session.add_all(
                    [agent, service, instance, event, conversation, turn]
                )
                await session.commit()
                session.add(operation)
                await session.commit()

                duplicate = Operation(
                    id=str(uuid4()),
                    organization_id="local",
                    instance_id=instance.id,
                    agent_id=agent.id,
                    source_event_id=event.id,
                    source_conversation_turn_id=turn.id,
                    conversation_request_id=request_id,
                    action_type="docker_restart",
                    status="failed",
                    active_key=None,
                    requested_by="local-admin",
                    risk_level="medium",
                    impact_summary="duplicate",
                    plan_snapshot={},
                    precheck_result={"passed": False},
                    verification_policy={},
                    idempotency_key=f"op_{uuid4().hex}",
                    expires_at=now + timedelta(minutes=5),
                )
                session.add(duplicate)
                with pytest.raises(IntegrityError):
                    await session.commit()
                await session.rollback()

                await session.execute(
                    delete(ConversationTurn).where(ConversationTurn.id == turn_id)
                )
                await session.commit()
                persisted = await session.get(Operation, operation_id)
                assert persisted is not None
                assert persisted.source_conversation_turn_id is None
                assert persisted.plan_snapshot["conversation_source"] == tombstone
        finally:
            async with factory() as session:
                await session.execute(
                    delete(Operation).where(Operation.id == operation_id)
                )
                await session.execute(
                    delete(Agent).where(Agent.id == agent_id)
                )
                await session.execute(
                    delete(ManagedService).where(ManagedService.id == service_id)
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
