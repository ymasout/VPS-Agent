import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.dialects import postgresql

import app.conversation as conversation_module
from app.config import Settings
from app.conversation import (
    create_scoped_conversation_turn,
    get_agent_conversation,
    get_service_conversation,
    scoped_agent,
    scoped_service_instance,
)
from app.models import (
    Agent,
    ConversationSession,
    ConversationTurn,
    ManagedService,
    Operation,
    ServiceInstance,
)
from app.schemas import ConversationQuestion, ConversationTurnView


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def context_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"conversation_context_chat_enabled": True}
    values.update(overrides)
    return Settings(**values)


def test_context_conversation_is_default_off() -> None:
    assert Settings().conversation_context_chat_enabled is False


def test_agent_without_conversation_returns_200_empty_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(id="agent-1", organization_id="local", name="edge")
    session = AsyncMock()
    session.scalar.return_value = None
    monkeypatch.setattr(
        conversation_module,
        "scoped_agent",
        AsyncMock(return_value=agent),
    )

    view = asyncio.run(
        get_agent_conversation("agent-1", session, context_settings())
    )

    assert view.scope_type == "agent"
    assert view.target_id == "agent-1"
    assert view.parent_agent_id == "agent-1"
    assert view.session_id is None
    assert view.available is True
    assert view.turns == []


def test_service_route_derives_service_scope_from_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = ServiceInstance(
        id="instance-1",
        service_id="service-1",
        agent_id="agent-1",
    )
    service = ManagedService(
        id="service-1",
        organization_id="local",
        name="api",
    )
    session = AsyncMock()
    session.scalar.return_value = None
    monkeypatch.setattr(
        conversation_module,
        "scoped_service_instance",
        AsyncMock(return_value=(instance, service)),
    )

    view = asyncio.run(
        get_service_conversation("instance-1", session, context_settings())
    )

    assert view.scope_type == "service"
    assert view.target_id == "service-1"
    assert view.parent_agent_id == "agent-1"
    assert view.title == "api"
    assert view.turns == []


@pytest.mark.parametrize(
    ("scope_type", "target_id"),
    [("agent", "agent-1"), ("service", "service-1")],
)
def test_context_turn_only_persists_conversation_records(
    monkeypatch: pytest.MonkeyPatch,
    scope_type: str,
    target_id: str,
) -> None:
    conversation = ConversationSession(
        id="session-1",
        organization_id="local",
        scope_type=scope_type,
        event_id=None,
        repository_id=None,
        agent_id=target_id if scope_type == "agent" else None,
        service_id=target_id if scope_type == "service" else None,
        created_by="local-admin",
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    session = AsyncMock()
    session.scalar.side_effect = [conversation, None, None]
    session.add = MagicMock()
    nested = AsyncMock()
    session.begin_nested = MagicMock(return_value=nested)
    monkeypatch.setattr(
        conversation_module,
        "turn_view",
        AsyncMock(
            return_value=ConversationTurnView(
                id="turn-1",
                session_id=conversation.id,
                client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                question="safe",
                status="pending",
                provider="deterministic",
                answer=None,
                citations=[],
                context_manifest={},
                error_code=None,
                error_detail=None,
                created_at=now_utc(),
                started_at=None,
                completed_at=None,
            )
        ),
    )
    background = BackgroundTasks()

    asyncio.run(
        create_scoped_conversation_turn(
            scope_type=scope_type,
            target_id=target_id,
            payload=ConversationQuestion(
                client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                question="fix it password=do-not-store",
            ),
            background_tasks=background,
            session=session,
            settings=context_settings(),
        )
    )

    persisted = [call.args[0] for call in session.add.call_args_list]
    assert len(persisted) == 1
    assert isinstance(persisted[0], ConversationTurn)
    assert not any(isinstance(item, Operation) for item in persisted)
    assert "do-not-store" not in persisted[0].question
    assert len(background.tasks) == 1
    assert background.tasks[0].func is conversation_module.run_conversation_turn


def test_context_turn_is_blocked_by_feature_flag() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_scoped_conversation_turn(
                scope_type="agent",
                target_id="agent-1",
                payload=ConversationQuestion(
                    client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                    question="status",
                ),
                background_tasks=BackgroundTasks(),
                session=AsyncMock(),
                settings=context_settings(conversation_context_chat_enabled=False),
            )
        )
    assert error.value.status_code == 403
    assert error.value.detail == "feature_disabled"


def test_scope_queries_include_organization_filters() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    with pytest.raises(HTTPException):
        asyncio.run(scoped_agent(session, "agent-1", "other-org"))
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "agents.organization_id" in sql

    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session.execute.return_value = result
    with pytest.raises(HTTPException):
        asyncio.run(scoped_service_instance(session, "instance-1", "other-org"))
    query = session.execute.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "managed_services.organization_id" in sql
    assert "agents.organization_id" in sql
