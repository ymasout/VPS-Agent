import asyncio
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.dialects import postgresql

import app.conversation as conversation_module
import app.repository_knowledge as repository_module
from app.config import Settings
from app.conversation import (
    ContextItem,
    create_repository_conversation_turn,
    get_repository_conversation,
    validate_answer_citations,
)
from app.models import (
    ConversationSession,
    ConversationTurn,
    GitHubRepositoryBinding,
    GitHubRepositoryFile,
    Operation,
    Repository,
)
from app.repository_knowledge import (
    RepositoryKnowledgeItem,
    RepositorySnapshotState,
    repository_knowledge_for_repository,
    repository_snapshot_item_is_current,
)
from app.schemas import (
    ConversationAnswer,
    ConversationQuestion,
    RepositoryDetailView,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "conversation_repository_chat_enabled": True,
        "github_app_id": "123",
        "github_app_private_key_base64": "test-only",
        "github_app_installation_id": 42,
        "github_webhook_secret": "test-only",
    }
    values.update(overrides)
    return Settings(**values)


def repository_state() -> RepositorySnapshotState:
    now = now_utc()
    repository = Repository(
        id="repository-1",
        organization_id="local",
        full_name="owner/repository",
        default_branch="main",
    )
    binding = GitHubRepositoryBinding(
        id="binding-1",
        repository_id=repository.id,
        installation_id=42,
        github_repository_id=1234,
        private=True,
        enabled=True,
        head_sha="a" * 40,
        synchronized_at=now,
        last_error=None,
    )
    content = "services:\n  api:\n    healthcheck: curl /healthz\n"
    file = GitHubRepositoryFile(
        id="file-1",
        repository_id=repository.id,
        commit_sha=binding.head_sha,
        path="compose.yaml",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        byte_size=len(content.encode()),
        redacted=True,
        truncated=False,
        fetched_at=now,
    )
    return RepositorySnapshotState(
        repository=repository,
        binding=binding,
        files=[file],
        available=True,
        unavailable_reason=None,
    )


def knowledge_item(
    *, basis: str = "snapshot", relation: str = "unknown"
) -> RepositoryKnowledgeItem:
    state = repository_state()
    file = state.files[0]
    return RepositoryKnowledgeItem(
        repository_file_id=file.id,
        repository_id=state.repository.id,
        full_name=state.repository.full_name,
        path=file.path,
        repository_commit_sha=file.commit_sha,
        deployment_commit_sha=None if basis == "snapshot" else "b" * 40,
        deployment_relation=relation,
        content_sha256=file.content_sha256,
        excerpt="healthcheck: curl /healthz",
        fetched_at=file.fetched_at,
        synchronized_at=state.binding.synchronized_at if state.binding else None,
        truncated=False,
        stale=False,
        basis=basis,
    )


def context_item(item: RepositoryKnowledgeItem) -> ContextItem:
    return ContextItem(
        citation_id="ctx_0123456789abcdef01234567",
        source_type="repository_file",
        target_id=item.repository_file_id,
        source_label="GitHub owner/repository · compose.yaml",
        content="healthcheck: curl /healthz",
        collected_at=item.fetched_at,
        snapshot_sha256="a" * 64,
        truncated=False,
        repository=item,
    )


def answer(citation: str) -> ConversationAnswer:
    return ConversationAnswer.model_validate(
        {
            "summary": "snapshot answer",
            "facts": [{"statement": "snapshot contains a healthcheck", "citation_ids": [citation]}],
            "inferences": [],
            "recommendations": [],
            "missing_evidence": [],
        }
    )


def scalar_rows(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


def detail(*, available: bool = True) -> RepositoryDetailView:
    state = repository_state()
    return RepositoryDetailView(
        id=state.repository.id,
        full_name=state.repository.full_name,
        default_branch=state.repository.default_branch,
        private=True,
        enabled=True,
        head_sha=state.binding.head_sha if state.binding else None,
        synchronized_at=state.binding.synchronized_at if state.binding else None,
        last_error=None,
        conversation_available=available,
        unavailable_reason=None if available else "feature_disabled",
        files=[],
    )


def test_repository_without_conversation_returns_200_empty_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    monkeypatch.setattr(
        conversation_module,
        "repository_detail",
        AsyncMock(return_value=detail()),
    )

    view = asyncio.run(
        get_repository_conversation("repository-1", session, settings())
    )

    assert view.repository_id == "repository-1"
    assert view.session_id is None
    assert view.available is True
    assert view.turns == []


def test_cross_organization_repository_is_hidden_as_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        conversation_module,
        "repository_snapshot_state",
        AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            conversation_module.get_repository_detail(
                "other-repository",
                session,
                settings(),
            )
        )

    assert error.value.status_code == 404


def test_repository_turn_only_persists_conversation_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = ConversationSession(
        id="session-1",
        organization_id="local",
        scope_type="repository",
        event_id=None,
        repository_id="repository-1",
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
        "repository_detail",
        AsyncMock(return_value=detail()),
    )
    monkeypatch.setattr(
        conversation_module,
        "turn_view",
        AsyncMock(return_value="turn-view"),
    )
    background = BackgroundTasks()

    result = asyncio.run(
        create_repository_conversation_turn(
            "repository-1",
            ConversationQuestion(
                client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                question="fix it password=do-not-store",
            ),
            background,
            session,
            settings(),
        )
    )

    persisted = [call.args[0] for call in session.add.call_args_list]
    assert result == "turn-view"
    assert len(persisted) == 1
    assert isinstance(persisted[0], ConversationTurn)
    assert not any(isinstance(item, Operation) for item in persisted)
    assert "do-not-store" not in persisted[0].question
    assert len(background.tasks) == 1
    assert background.tasks[0].func is conversation_module.run_conversation_turn


def test_repository_turn_is_blocked_by_independent_feature_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conversation_module,
        "repository_detail",
        AsyncMock(return_value=detail(available=False)),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_repository_conversation_turn(
                "repository-1",
                ConversationQuestion(
                    client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                    question="healthcheck",
                ),
                BackgroundTasks(),
                AsyncMock(),
                settings(conversation_repository_chat_enabled=False),
            )
        )

    assert error.value.status_code == 403
    assert error.value.detail == "feature_disabled"


def test_snapshot_citation_can_support_snapshot_fact_but_mismatch_deployment_cannot() -> None:
    snapshot = context_item(knowledge_item())
    validate_answer_citations(answer(snapshot.citation_id), [snapshot])

    mismatch = context_item(knowledge_item(basis="deployment", relation="mismatch"))
    with pytest.raises(Exception, match="not aligned"):
        validate_answer_citations(answer(mismatch.citation_id), [mismatch])


def test_repository_retrieval_is_single_scope_and_marks_snapshot_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = repository_state()
    monkeypatch.setattr(
        repository_module,
        "repository_snapshot_state",
        AsyncMock(return_value=state),
    )

    returned_state, items = asyncio.run(
        repository_knowledge_for_repository(
            AsyncMock(),
            state.repository.id,
            "local",
            "compose.yaml healthcheck",
            settings(),
        )
    )

    assert returned_state == state
    assert len(items) == 1
    assert items[0].repository_id == state.repository.id
    assert items[0].basis == "snapshot"
    assert items[0].deployment_commit_sha is None
    assert items[0].deployment_relation == "unknown"


def test_repository_snapshot_revalidation_filters_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = repository_state()
    session = AsyncMock()
    session.scalar.return_value = state.files[0]
    monkeypatch.setattr(
        repository_module,
        "repository_snapshot_state",
        AsyncMock(return_value=state),
    )

    current = asyncio.run(
        repository_snapshot_item_is_current(
            session,
            state.repository.id,
            "local",
            knowledge_item(),
            settings(),
        )
    )

    assert current is True
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "repositories.organization_id" in sql
