import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.operations as operations_module
from app.config import Settings
from app.models import (
    Agent,
    ManagedService,
    Operation,
    OperationTransition,
    ServiceInstance,
)
from app.operations import build_restart_plan
from app.principal import (
    EVENT_READ,
    FLEET_READ,
    OPERATION_PLAN,
    OPERATION_READ,
    SYSTEM_READ,
    Principal,
)

POSTGRES_URL = os.getenv("M6_TEST_DATABASE_URL")
API_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M6_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_named_actor_snapshot_blocks_downgrade() -> None:
    operation_id = str(uuid4())
    transition_id = str(uuid4())
    principal_snapshot = {
        "principal_id": "local:4bf4ab08-4da6-44bb-8607-3c87f1946012",
        "display_name": "Alice",
        "auth_source": "caddy_basic",
        "auth_subject": "ops-alice",
        "organization_id": "local",
        "roles": ["operator"],
        "capability_used": "operation:plan",
    }

    async def seed() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                instance = await session.scalar(select(ServiceInstance).limit(1))
                agent_id = await session.scalar(select(Agent.id).limit(1))
                assert instance is not None and agent_id is not None
                session.add(
                    Operation(
                        id=operation_id,
                        instance_id=instance.id,
                        agent_id=agent_id,
                        action_type="docker_restart",
                        status="awaiting_confirmation",
                        requested_by=principal_snapshot["principal_id"],
                        requested_principal_snapshot=principal_snapshot,
                        authorization_mode="named",
                        risk_level="medium",
                        impact_summary="migration downgrade guard fixture",
                        plan_snapshot={},
                        precheck_result={},
                        verification_policy={},
                        idempotency_key=f"m6-named-{operation_id}",
                        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    )
                )
                session.add(
                    OperationTransition(
                        id=transition_id,
                        operation_id=operation_id,
                        from_status=None,
                        to_status="awaiting_confirmation",
                        actor_type="principal",
                        actor_id=principal_snapshot["principal_id"],
                        actor_principal_snapshot=principal_snapshot,
                        details={},
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    async def cleanup() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                await session.execute(delete(Operation).where(Operation.id == operation_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic.ini",
                "downgrade",
                "0019_m6_multichannel_notify",
            ],
            cwd=API_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "named approval audit exists" in result.stderr
    finally:
        asyncio.run(cleanup())


def test_named_restart_plan_persists_actor_and_stops_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = Principal(
        id="local:4bf4ab08-4da6-44bb-8607-3c87f1946012",
        display_name="Alice",
        auth_source="caddy_basic",
        auth_subject="ops-alice",
        organization_id="local",
        roles=("operator",),
        capabilities=frozenset(
            {SYSTEM_READ, FLEET_READ, EVENT_READ, OPERATION_READ, OPERATION_PLAN}
        ),
        authorization_mode="read_enforced",
        write_authorization_mode="enforced",
    )

    async def exercise() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        operation_id: str | None = None
        try:
            async with factory() as session:
                instance = await session.scalar(select(ServiceInstance).limit(1))
                assert instance is not None
                agent = await session.get(Agent, instance.agent_id)
                managed = await session.get(ManagedService, instance.service_id)
                assert agent is not None and managed is not None

                async def passing_prechecks(*_args: object):
                    return {"passed": True}, agent, managed, None

                monkeypatch.setattr(
                    operations_module, "run_prechecks", passing_prechecks
                )
                operation = await build_restart_plan(
                    session,
                    instance,
                    None,
                    None,
                    Settings(skip_database_init=True),
                    expires_in_seconds=300,
                    requester=principal,
                )
                operation_id = operation.id
                assert operation.status == "awaiting_confirmation"
                assert operation.authorization_mode == "named"
                assert operation.requested_by == principal.id
                assert operation.requested_principal_snapshot == principal.snapshot(
                    OPERATION_PLAN
                )
                assert operation.confirmed_by is None
                assert operation.task_nonce is None
                assert operation.task_signature is None
                initial = await session.scalar(
                    select(OperationTransition).where(
                        OperationTransition.operation_id == operation.id,
                        OperationTransition.from_status.is_(None),
                    )
                )
                assert initial is not None
                assert initial.actor_type == "principal"
                assert initial.actor_id == principal.id
                assert initial.actor_principal_snapshot == principal.snapshot(OPERATION_PLAN)
        finally:
            if operation_id is not None:
                async with factory() as session:
                    await session.execute(
                        delete(Operation).where(Operation.id == operation_id)
                    )
                    await session.commit()
            await engine.dispose()

    asyncio.run(exercise())
