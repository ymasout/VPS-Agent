import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timezone
from typing import Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from .config import Settings, get_settings
from .schema import (
    current_revisions,
    expected_revisions,
    verify_adoption_candidate,
    verify_database_current,
)

FORMAT_VERSION = "m6.1-control-plane-backup-v1"
KEY_TABLE_ALLOWLIST = (
    "agents",
    "managed_services",
    "service_instances",
    "alert_events",
    "diagnostic_runs",
    "evidence_items",
    "operations",
    "operation_transitions",
    "conversation_sessions",
    "conversation_turns",
    "github_repository_bindings",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DumpFile(StrictModel):
    name: Literal["postgres.dump"] = "postgres.dump"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class BackupManifest(StrictModel):
    format_version: Literal[FORMAT_VERSION] = FORMAT_VERSION
    instance_id: str = Field(min_length=1, max_length=128)
    created_at: datetime
    control_plane_version: str
    control_plane_commit_sha: str
    control_plane_build_time: str
    alembic_revision: list[str]
    expected_alembic_revision: list[str]
    postgres_major: int = Field(ge=12, le=99)
    database_name: str
    database_role: str
    required_extensions: list[str]
    key_table_counts: dict[str, int]
    active_operation_count: int = Field(ge=0)
    snapshot_note: Literal[
        "consistent snapshot may include operations that were in flight when backup started"
    ]
    label: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
    dump: DumpFile

    @field_validator("key_table_counts")
    @classmethod
    def validate_key_table_allowlist(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != set(KEY_TABLE_ALLOWLIST):
            raise ValueError("key-table counts must use the fixed M6.1 allowlist")
        if any(count < 0 for count in value.values()):
            raise ValueError("key-table counts must not be negative")
        return {name: value[name] for name in KEY_TABLE_ALLOWLIST}


class SnapshotMetadata(StrictModel):
    snapshot_id: str
    release_channel: str
    instance_id: str
    created_at: datetime
    control_plane_version: str
    control_plane_commit_sha: str
    control_plane_build_time: str
    alembic_revision: list[str]
    expected_alembic_revision: list[str]
    postgres_major: int
    database_name: str
    database_role: str
    required_extensions: list[str]
    key_table_counts: dict[str, int]
    active_operation_count: int
    snapshot_note: str


class RestoreSummary(StrictModel):
    format_version: Literal["m6.1-control-plane-restore-v1"] = (
        "m6.1-control-plane-restore-v1"
    )
    instance_id: str
    restored_at: datetime
    source_created_at: datetime
    control_plane_version: str
    control_plane_commit_sha: str
    alembic_revision: list[str]
    schema_current: bool
    key_table_counts_match: bool
    active_operation_count: int


async def _database_metadata(connection: AsyncConnection, settings: Settings) -> dict:
    url = make_url(settings.database_url)
    revision = sorted(await current_revisions(connection))
    server_version = int(await connection.scalar(text("SHOW server_version_num")))
    extensions = list(
        (
            await connection.execute(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname <> 'plpgsql' ORDER BY extname"
                )
            )
        ).scalars()
    )
    counts: dict[str, int] = {}
    for table_name in KEY_TABLE_ALLOWLIST:
        counts[table_name] = int(
            await connection.scalar(text(f'SELECT count(*) FROM "{table_name}"')) or 0
        )
    active_operations = int(
        await connection.scalar(
            text("SELECT count(*) FROM operations WHERE active_key IS NOT NULL")
        )
        or 0
    )
    return {
        "instance_id": settings.control_plane_instance_id,
        "created_at": datetime.now(timezone.utc),
        "control_plane_version": settings.control_plane_version,
        "control_plane_commit_sha": settings.control_plane_commit_sha,
        "control_plane_build_time": settings.control_plane_build_time,
        "alembic_revision": revision,
        "expected_alembic_revision": sorted(expected_revisions()),
        "postgres_major": server_version // 10000,
        "database_name": url.database or "",
        "database_role": url.username or "",
        "required_extensions": extensions,
        "key_table_counts": counts,
        "active_operation_count": active_operations,
        "snapshot_note": (
            "consistent snapshot may include operations that were in flight when backup started"
        ),
    }


async def export_snapshot() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    url = make_url(settings.database_url)
    release_channel = f"m6_backup_{secrets.token_hex(8)}"
    released = asyncio.Event()

    def receive_release(*_: object) -> None:
        released.set()

    listener = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    await listener.add_listener(release_channel, receive_release)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                snapshot_id = str(
                    await connection.scalar(text("SELECT pg_export_snapshot()"))
                )
                payload = SnapshotMetadata(
                    snapshot_id=snapshot_id,
                    release_channel=release_channel,
                    **(await _database_metadata(connection, settings)),
                )
                print(payload.model_dump_json(), flush=True)
                await asyncio.wait_for(released.wait(), timeout=600)
            finally:
                await transaction.rollback()
    finally:
        await listener.close()
        await engine.dispose()


def _load_stdin(model: type[StrictModel]) -> StrictModel:
    return model.model_validate_json(sys.stdin.read())


def finalize_manifest(label: str, dump_sha256: str, dump_size: int) -> None:
    snapshot = _load_stdin(SnapshotMetadata)
    values = snapshot.model_dump(exclude={"snapshot_id", "release_channel"})
    manifest = BackupManifest(
        **values,
        label=label,
        dump=DumpFile(sha256=dump_sha256, size_bytes=dump_size),
    )
    print(manifest.model_dump_json(indent=2))


def validate_manifest() -> None:
    manifest = _load_stdin(BackupManifest)
    settings = get_settings()
    errors: list[str] = []
    if manifest.instance_id != settings.control_plane_instance_id:
        errors.append("control-plane instance id does not match backup")
    if manifest.control_plane_version != settings.control_plane_version:
        errors.append("control-plane version does not match backup")
    if manifest.control_plane_commit_sha != settings.control_plane_commit_sha:
        errors.append("control-plane commit does not match backup")
    if manifest.postgres_major != 16:
        errors.append("backup PostgreSQL major is unsupported by M6.1")
    if manifest.expected_alembic_revision != sorted(expected_revisions()):
        errors.append("application Alembic head is incompatible with backup")
    if manifest.alembic_revision not in ([], sorted(expected_revisions())):
        errors.append("backup Alembic revision is incompatible with application head")
    if set(manifest.key_table_counts) != set(KEY_TABLE_ALLOWLIST):
        errors.append("manifest key-table allowlist is invalid")
    if errors:
        raise RuntimeError("; ".join(errors))
    print("backup manifest is compatible with this control-plane build")


async def release_snapshot(channel: str) -> None:
    if not channel.startswith("m6_backup_") or not channel.removeprefix(
        "m6_backup_"
    ).isalnum():
        raise RuntimeError("invalid backup release channel")
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_notify(:channel, 'release')"), {"channel": channel}
            )
    finally:
        await engine.dispose()


async def validate_target() -> None:
    manifest = _load_stdin(BackupManifest)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            url = make_url(settings.database_url)
            server_version = int(await connection.scalar(text("SHOW server_version_num")))
            available_extensions = set(
                (
                    await connection.execute(
                        text(
                            "SELECT name FROM pg_available_extensions ORDER BY name"
                        )
                    )
                ).scalars()
            )
            object_count = int(
                await connection.scalar(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM pg_class c "
                        " JOIN pg_namespace n ON n.oid = c.relnamespace "
                        " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        " AND n.nspname NOT LIKE 'pg_toast%' "
                        " AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')) + "
                        "(SELECT count(*) FROM pg_proc p "
                        " JOIN pg_namespace n ON n.oid = p.pronamespace "
                        " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')) + "
                        "(SELECT count(*) FROM pg_type t "
                        " JOIN pg_namespace n ON n.oid = t.typnamespace "
                        " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        " AND t.typtype IN ('d', 'e', 'm', 'r')) + "
                        "(SELECT count(*) FROM pg_namespace "
                        " WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema') "
                        " AND nspname NOT LIKE 'pg_toast%' "
                        " AND nspname NOT LIKE 'pg_temp_%')"
                    )
                )
                or 0
            )
            errors: list[str] = []
            if object_count:
                errors.append("target database contains non-system objects")
            if server_version // 10000 != manifest.postgres_major:
                errors.append("target PostgreSQL major does not match backup")
            if (url.database or "") != manifest.database_name:
                errors.append("target database name does not match backup")
            if (url.username or "") != manifest.database_role:
                errors.append("target database role does not match backup")
            missing_extensions = sorted(
                set(manifest.required_extensions) - available_extensions
            )
            if missing_extensions:
                errors.append("target PostgreSQL is missing required extension support")
            if errors:
                raise RuntimeError("; ".join(errors))
            print("restore target is empty and compatible")
    finally:
        await engine.dispose()


async def verify_restored() -> None:
    manifest = _load_stdin(BackupManifest)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            if manifest.alembic_revision:
                await verify_database_current(connection, compare_schema=True)
            else:
                await verify_adoption_candidate(connection)
            metadata = await _database_metadata(connection, settings)
            if metadata["key_table_counts"] != manifest.key_table_counts:
                raise RuntimeError("restored key-table counts do not match manifest")
            summary = RestoreSummary(
                instance_id=manifest.instance_id,
                restored_at=datetime.now(timezone.utc),
                source_created_at=manifest.created_at,
                control_plane_version=manifest.control_plane_version,
                control_plane_commit_sha=manifest.control_plane_commit_sha,
                alembic_revision=metadata["alembic_revision"],
                schema_current=(
                    metadata["alembic_revision"] == sorted(expected_revisions())
                ),
                key_table_counts_match=True,
                active_operation_count=manifest.active_operation_count,
            )
            print(summary.model_dump_json(indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="M6.1 control-plane recovery metadata")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("export-snapshot")
    finalize = subparsers.add_parser("finalize-manifest")
    finalize.add_argument("--label", required=True)
    finalize.add_argument("--dump-sha256", required=True)
    finalize.add_argument("--dump-size", required=True, type=int)
    subparsers.add_parser("validate-manifest")
    release = subparsers.add_parser("release-snapshot")
    release.add_argument("channel")
    subparsers.add_parser("validate-target")
    subparsers.add_parser("verify-restored")
    args = parser.parse_args()
    if args.command == "export-snapshot":
        asyncio.run(export_snapshot())
    elif args.command == "finalize-manifest":
        finalize_manifest(args.label, args.dump_sha256, args.dump_size)
    elif args.command == "validate-manifest":
        validate_manifest()
    elif args.command == "release-snapshot":
        asyncio.run(release_snapshot(args.channel))
    elif args.command == "validate-target":
        asyncio.run(validate_target())
    else:
        asyncio.run(verify_restored())


if __name__ == "__main__":
    main()
