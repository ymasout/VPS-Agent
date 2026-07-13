import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import agent_is_online, register_agent
from app.config import Settings
from app.models import Agent, RegistrationToken
from app.schemas import AgentRegister


def test_reenrollment_boundary_blocks_online_machine() -> None:
    current_time = datetime.now(timezone.utc)

    assert agent_is_online(current_time - timedelta(seconds=30), current_time, 90)
    assert not agent_is_online(current_time - timedelta(seconds=120), current_time, 90)
    assert not agent_is_online(None, current_time, 90)


def registration_payload() -> AgentRegister:
    return AgentRegister(
        token="reg_recovery_token_value",
        name="recovered-vps",
        hostname="vm-01",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.2.3",
        capabilities=["host.metrics"],
    )


def existing_agent(last_seen_at: datetime) -> Agent:
    return Agent(
        id="agent-01",
        credential_hash="old-hash",
        name="old-name",
        hostname="vm-01",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.2.2",
        capabilities=[],
        last_seen_at=last_seen_at,
    )


def valid_token() -> RegistrationToken:
    return RegistrationToken(
        token_hash="token-hash",
        name="recovered-vps",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_offline_machine_can_recover_identity() -> None:
    token = valid_token()
    agent = existing_agent(datetime.now(timezone.utc) - timedelta(minutes=5))
    session = AsyncMock()
    session.scalar.side_effect = [token, agent]

    result = asyncio.run(
        register_agent(registration_payload(), session, Settings(skip_database_init=True))
    )

    assert result.agent_id == "agent-01"
    assert agent.credential_hash != "old-hash"
    assert agent.name == "recovered-vps"
    assert token.used_at is not None
    session.commit.assert_awaited_once()


def test_online_machine_cannot_be_rebound() -> None:
    token = valid_token()
    session = AsyncMock()
    session.scalar.side_effect = [token, existing_agent(datetime.now(timezone.utc))]

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            register_agent(registration_payload(), session, Settings(skip_database_init=True))
        )

    assert error.value.status_code == 409
    assert "already online" in error.value.detail
    assert token.used_at is None
