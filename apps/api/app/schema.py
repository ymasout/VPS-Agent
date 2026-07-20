import argparse
import asyncio
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from .config import get_settings
from .models import Base

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG_PATH = API_ROOT / "alembic.ini"


class SchemaStateError(RuntimeError):
    pass


def expected_revisions() -> set[str]:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _has_version_table(connection: Connection) -> bool:
    return inspect(connection).has_table("alembic_version")


def _schema_differences(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


async def current_revisions(connection: AsyncConnection) -> set[str]:
    if not await connection.run_sync(_has_version_table):
        return set()
    result = await connection.execute(text("SELECT version_num FROM alembic_version"))
    return set(result.scalars())


async def verify_database_current(
    connection: AsyncConnection, *, compare_schema: bool = False
) -> None:
    current = await current_revisions(connection)
    expected = expected_revisions()
    if current != expected:
        raise SchemaStateError(
            "database revision mismatch: "
            f"current={sorted(current) or ['unversioned']} expected={sorted(expected)}; "
            "run the explicit Alembic adoption or migration step before starting the API"
        )
    if compare_schema:
        differences = await connection.run_sync(_schema_differences)
        if differences:
            raise SchemaStateError(
                "database schema differs from the application model "
                f"({len(differences)} differences)"
            )


async def verify_adoption_candidate(connection: AsyncConnection) -> None:
    current = await current_revisions(connection)
    if current:
        raise SchemaStateError(
            f"database is already managed by Alembic at revisions {sorted(current)}"
        )
    differences = await connection.run_sync(_schema_differences)
    if differences:
        raise SchemaStateError(
            "refusing to stamp an incomplete create_all database: "
            f"schema has {len(differences)} differences from the application model"
        )


async def run_cli(command: str) -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            if command == "verify-adoption":
                await verify_adoption_candidate(connection)
                print("schema matches the application model and is safe to stamp")
            elif command == "revisions":
                current = await current_revisions(connection)
                print(f"current={','.join(sorted(current)) if current else 'unversioned'}")
                print(f"head={','.join(sorted(expected_revisions()))}")
            else:
                await verify_database_current(connection, compare_schema=True)
                print("database revision and schema match the application")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate control-plane database ownership")
    parser.add_argument("command", choices=("verify-adoption", "check", "revisions"))
    args = parser.parse_args()
    asyncio.run(run_cli(args.command))


if __name__ == "__main__":
    main()
