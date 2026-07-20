import argparse
import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.models import Agent, Base, ManagedService, ServiceInstance


async def create_fixture() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(
                Agent(
                    id="adoption-agent",
                    credential_hash="a" * 64,
                    name="adoption-agent",
                    hostname="adoption-host",
                    machine_id="adoption-machine",
                    os="linux",
                    arch="amd64",
                    version="0.3.3",
                    capabilities=[],
                )
            )
            session.add(
                ManagedService(
                    id="adoption-service",
                    name="adoption-service",
                    criticality="critical",
                )
            )
            await session.flush()
            session.add(
                ServiceInstance(
                    id="adoption-instance",
                    service_id="adoption-service",
                    agent_id="adoption-agent",
                    service_kind="docker",
                    service_key="compose:adoption:canary:1",
                    restart_enabled=False,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def assert_fixture() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            agent_count = await session.scalar(
                select(func.count()).select_from(Agent).where(Agent.id == "adoption-agent")
            )
            service = await session.get(ManagedService, "adoption-service")
            instance = await session.get(ServiceInstance, "adoption-instance")
            if agent_count != 1 or service is None or instance is None:
                raise RuntimeError("create_all adoption did not preserve fixture rows")
            if service.criticality != "critical" or instance.restart_enabled:
                raise RuntimeError("create_all adoption changed conservative operation defaults")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "assert"))
    args = parser.parse_args()
    asyncio.run(create_fixture() if args.command == "create" else assert_fixture())


if __name__ == "__main__":
    main()
