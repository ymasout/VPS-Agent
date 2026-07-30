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

from app.models import Agent, Operation, OperationTransition, ServiceInstance

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
