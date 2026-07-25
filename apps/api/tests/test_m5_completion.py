import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.config import Settings
from app.conversation import citation_target
from app.conversation_completion import (
    _fleet_snapshot_sha256,
    create_fleet_conversation_turn,
    create_runbook_draft,
    get_event_history,
    get_event_review,
    get_fleet_conversation,
    get_similar_events,
    put_conversation_feedback,
)
from app.main import app
from app.schemas import (
    ConversationFeedbackUpdate,
    ConversationQuestion,
    RunbookDraftCreate,
)


def test_completion_features_are_default_off() -> None:
    settings = Settings()
    assert settings.conversation_fleet_chat_enabled is False
    assert settings.conversation_insights_enabled is False
    assert settings.conversation_review_enabled is False


def test_fleet_without_session_returns_200_empty_turns() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    view = asyncio.run(
        get_fleet_conversation(
            session=session,
            settings=Settings(conversation_fleet_chat_enabled=True),
        )
    )
    assert view.session_id is None
    assert view.available is True
    assert view.turns == []


def test_fleet_turn_is_blocked_without_feature_flag() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_fleet_conversation_turn(
                payload=ConversationQuestion(
                    client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                    question="fleet status",
                ),
                background_tasks=BackgroundTasks(),
                session=AsyncMock(),
                settings=Settings(conversation_fleet_chat_enabled=False),
            )
        )
    assert error.value.status_code == 403
    assert error.value.detail == "feature_disabled"


@pytest.mark.parametrize(
    "call",
    [
        lambda session: get_event_history(
            "event-1", session=session, settings=Settings(), limit=50, cursor=None
        ),
        lambda session: get_similar_events(
            "event-1", session=session, settings=Settings(), limit=10, cursor=None
        ),
        lambda session: get_event_review(
            "event-1", session=session, settings=Settings()
        ),
    ],
)
def test_read_completion_endpoints_fail_closed_when_disabled(call) -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(call(AsyncMock()))
    assert error.value.status_code == 403
    assert error.value.detail == "feature_disabled"


def test_feedback_and_runbook_mutations_fail_closed_when_disabled() -> None:
    with pytest.raises(HTTPException) as feedback_error:
        asyncio.run(
            put_conversation_feedback(
                "turn-1",
                ConversationFeedbackUpdate(rating="helpful"),
                session=AsyncMock(),
                settings=Settings(),
            )
        )
    assert feedback_error.value.status_code == 403

    with pytest.raises(HTTPException) as draft_error:
        asyncio.run(
            create_runbook_draft(
                "turn-1",
                RunbookDraftCreate(
                    client_request_id="6fd98744-1d93-4555-b019-e075b0453f35",
                    recommendation_index=0,
                ),
                session=AsyncMock(),
                settings=Settings(),
            )
        )
    assert draft_error.value.status_code == 403


def test_runbook_request_rejects_executable_fields() -> None:
    with pytest.raises(ValidationError):
        RunbookDraftCreate.model_validate(
            {
                "client_request_id": "6fd98744-1d93-4555-b019-e075b0453f35",
                "recommendation_index": 0,
                "command": "rm -rf /",
                "agent_id": "other-agent",
            }
        )


def test_feedback_comment_has_utf8_budget() -> None:
    with pytest.raises(ValidationError):
        ConversationFeedbackUpdate(rating="not_helpful", comment="密" * 700)


def test_fleet_citation_target_only_sets_snapshot_id() -> None:
    target = citation_target("fleet_snapshot", "snapshot-1")
    assert target["fleet_snapshot_id"] == "snapshot-1"
    assert target["event_id"] is None
    assert target["operation_id"] is None
    assert target["repository_file_id"] is None


def test_fleet_snapshot_digest_covers_selected_source_ids() -> None:
    captured_at = datetime.now(timezone.utc)
    first = _fleet_snapshot_sha256(
        captured_at,
        {"agents_total": 1},
        {"agent_summary": ["agent-1"]},
        {"agent_summary": 0},
    )
    changed = _fleet_snapshot_sha256(
        captured_at,
        {"agents_total": 1},
        {"agent_summary": ["agent-2"]},
        {"agent_summary": 0},
    )
    assert first != changed


def test_completion_routes_use_v1_prefix_and_no_execute_endpoint() -> None:
    paths = {route.path for route in app.routes}
    expected = {
        "/api/v1/fleet/conversation",
        "/api/v1/fleet/conversation/turns",
        "/api/v1/events/{event_id}/history",
        "/api/v1/events/{event_id}/similar-events",
        "/api/v1/conversation-turns/{turn_id}/feedback",
        "/api/v1/events/{event_id}/review",
        "/api/v1/conversation-turns/{turn_id}/runbook-drafts",
        "/api/v1/runbook-drafts/{draft_id}",
    }
    assert expected <= paths
    assert not any("runbook" in path and "execute" in path for path in paths)


def test_feedback_normalizes_blank_comment() -> None:
    value = ConversationFeedbackUpdate(rating="helpful", comment="   ")
    assert value.comment is None
    assert datetime.now(timezone.utc).tzinfo is not None
