import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import current_agent, require_admin
from app.config import Settings
from app.models import Agent
from app.security import hash_token


def test_admin_authentication_rejects_missing_and_invalid_tokens() -> None:
    settings = Settings(admin_api_token="admin-secret", skip_database_init=True)

    for supplied in [None, "wrong-secret"]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(require_admin(supplied, settings))
        assert error.value.status_code == 401

    assert asyncio.run(require_admin("admin-secret", settings)) is None


def test_agent_authentication_rejects_missing_and_unknown_credentials() -> None:
    session = AsyncMock()

    for authorization in [None, "Basic value", "Bearer unknown"]:
        session.scalar.return_value = None
        with pytest.raises(HTTPException) as error:
            asyncio.run(current_agent(authorization, session))
        assert error.value.status_code == 401


def test_agent_authentication_returns_matching_agent() -> None:
    agent = Agent(
        id="agent-01",
        credential_hash=hash_token("agt_secret"),
        name="test-vps",
        hostname="vm-01",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.2.4",
        capabilities=[],
        last_seen_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.scalar.return_value = agent

    result = asyncio.run(current_agent("Bearer agt_secret", session))

    assert result is agent
