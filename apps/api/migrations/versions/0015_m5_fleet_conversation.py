"""M5.5 organization-scoped Fleet conversation snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0015_m5_fleet_conversation"
down_revision = "0014_m5_context_scope"
branch_labels = None
depends_on = None


OLD_SESSION_SCOPE_CHECK = (
    "("
    "(scope_type = 'event' AND event_id IS NOT NULL "
    "AND repository_id IS NULL AND agent_id IS NULL AND service_id IS NULL) OR "
    "(scope_type = 'repository' AND event_id IS NULL "
    "AND repository_id IS NOT NULL AND agent_id IS NULL AND service_id IS NULL) OR "
    "(scope_type = 'agent' AND event_id IS NULL "
    "AND repository_id IS NULL AND agent_id IS NOT NULL AND service_id IS NULL) OR "
    "(scope_type = 'service' AND event_id IS NULL "
    "AND repository_id IS NULL AND agent_id IS NULL AND service_id IS NOT NULL)"
    ")"
)

SESSION_SCOPE_CHECK = OLD_SESSION_SCOPE_CHECK[:-1] + (
    " OR (scope_type = 'fleet' AND event_id IS NULL "
    "AND repository_id IS NULL AND agent_id IS NULL AND service_id IS NULL))"
)

OLD_SOURCE_TYPE_CHECK = (
    "source_type IN ("
    "'alert_event', 'diagnostic_run', 'evidence_item', "
    "'agent_summary', 'service_instance_summary', 'operation', 'repository_file')"
)

SOURCE_TYPE_CHECK = OLD_SOURCE_TYPE_CHECK[:-1] + ", 'fleet_snapshot')"


def inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table_name: str) -> bool:
    return inspector().has_table(table_name)


def has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in inspector().get_columns(table_name)
    )


def has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspector().get_indexes(table_name)
    )


def has_constraint(table_name: str, constraint_name: str) -> bool:
    constraints = [
        *inspector().get_foreign_keys(table_name),
        *inspector().get_unique_constraints(table_name),
        *inspector().get_check_constraints(table_name),
    ]
    return any(item.get("name") == constraint_name for item in constraints)


def has_foreign_key_columns(table_name: str, columns: list[str]) -> bool:
    return any(
        item.get("constrained_columns") == columns
        for item in inspector().get_foreign_keys(table_name)
    )


def foreign_key_name(table_name: str, columns: list[str]) -> str | None:
    for item in inspector().get_foreign_keys(table_name):
        if item.get("constrained_columns") == columns:
            return item.get("name")
    return None


def source_target_check(*, include_fleet: bool) -> str:
    fleet_null = " AND fleet_snapshot_id IS NULL" if include_fleet else ""
    branches = [
        "(source_type = 'alert_event' AND event_id IS NOT NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
        "AND instance_id IS NULL AND operation_id IS NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'diagnostic_run' AND event_id IS NULL "
        "AND diagnostic_id IS NOT NULL AND evidence_id IS NULL AND agent_id IS NULL "
        "AND instance_id IS NULL AND operation_id IS NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'evidence_item' AND event_id IS NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NOT NULL AND agent_id IS NULL "
        "AND instance_id IS NULL AND operation_id IS NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'agent_summary' AND event_id IS NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NOT NULL "
        "AND instance_id IS NULL AND operation_id IS NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'service_instance_summary' AND event_id IS NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
        "AND instance_id IS NOT NULL AND operation_id IS NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'operation' AND event_id IS NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
        "AND instance_id IS NULL AND operation_id IS NOT NULL "
        f"AND repository_file_id IS NULL{fleet_null})",
        "(source_type = 'repository_file' AND event_id IS NULL "
        "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
        "AND instance_id IS NULL AND operation_id IS NULL "
        + ("AND fleet_snapshot_id IS NULL " if include_fleet else "")
        + "AND repository_full_name IS NOT NULL AND repository_path IS NOT NULL "
        "AND repository_commit_sha IS NOT NULL "
        "AND repository_deployment_relation IS NOT NULL "
        "AND repository_truncated IS NOT NULL AND repository_stale IS NOT NULL)",
    ]
    if include_fleet:
        branches.append(
            "(source_type = 'fleet_snapshot' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL)"
        )
    return "(" + " OR ".join(branches) + ")"


def upgrade() -> None:
    if has_constraint("conversation_sessions", "ck_conversation_sessions_scope_target"):
        op.drop_constraint(
            "ck_conversation_sessions_scope_target",
            "conversation_sessions",
            type_="check",
        )
    op.create_check_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        SESSION_SCOPE_CHECK,
    )
    if not has_index(
        "conversation_sessions", "uq_conversation_sessions_organization_fleet"
    ):
        op.create_index(
            "uq_conversation_sessions_organization_fleet",
            "conversation_sessions",
            ["organization_id"],
            unique=True,
            postgresql_where=sa.text("scope_type = 'fleet'"),
        )

    if not has_table("fleet_conversation_snapshots"):
        op.create_table(
            "fleet_conversation_snapshots",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("turn_id", sa.String(length=36), nullable=False),
            sa.Column("schema_version", sa.String(length=64), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("counts", sa.JSON(), nullable=False),
            sa.Column("selected_source_ids", sa.JSON(), nullable=False),
            sa.Column("omitted_counts", sa.JSON(), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ["turn_id", "organization_id"],
                ["conversation_turns.id", "conversation_turns.organization_id"],
                name="fk_fleet_conversation_snapshots_turn_organization",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "turn_id", name="uq_fleet_conversation_snapshots_turn"
            ),
            sa.UniqueConstraint(
                "id",
                "organization_id",
                "turn_id",
                name="uq_fleet_conversation_snapshots_identity_scope",
            ),
        )
    if not has_index(
        "fleet_conversation_snapshots",
        "ix_fleet_conversation_snapshots_organization_id",
    ):
        op.create_index(
            "ix_fleet_conversation_snapshots_organization_id",
            "fleet_conversation_snapshots",
            ["organization_id"],
        )
    if not has_index(
        "fleet_conversation_snapshots", "ix_fleet_conversation_snapshots_turn_id"
    ):
        op.create_index(
            "ix_fleet_conversation_snapshots_turn_id",
            "fleet_conversation_snapshots",
            ["turn_id"],
        )

    if not has_column("conversation_citations", "fleet_snapshot_id"):
        op.add_column(
            "conversation_citations",
            sa.Column("fleet_snapshot_id", sa.String(length=36), nullable=True),
        )
    if has_constraint("conversation_citations", "ck_conversation_citations_source_type"):
        op.drop_constraint(
            "ck_conversation_citations_source_type",
            "conversation_citations",
            type_="check",
        )
    if has_constraint("conversation_citations", "ck_conversation_citations_source_target"):
        op.drop_constraint(
            "ck_conversation_citations_source_target",
            "conversation_citations",
            type_="check",
        )
    op.create_check_constraint(
        "ck_conversation_citations_source_type",
        "conversation_citations",
        SOURCE_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_conversation_citations_source_target",
        "conversation_citations",
        source_target_check(include_fleet=True),
    )
    if not has_foreign_key_columns("conversation_citations", ["fleet_snapshot_id"]):
        op.create_foreign_key(
            "fk_conversation_citations_fleet_snapshot",
            "conversation_citations",
            "fleet_conversation_snapshots",
            ["fleet_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not has_index(
        "conversation_citations", "ix_conversation_citations_fleet_snapshot_id"
    ):
        op.create_index(
            "ix_conversation_citations_fleet_snapshot_id",
            "conversation_citations",
            ["fleet_snapshot_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    fleet_sessions = bind.execute(
        sa.text("SELECT count(*) FROM conversation_sessions WHERE scope_type = 'fleet'")
    ).scalar_one()
    if fleet_sessions:
        raise RuntimeError("cannot downgrade while Fleet conversations exist")
    op.drop_index(
        "ix_conversation_citations_fleet_snapshot_id",
        table_name="conversation_citations",
    )
    fleet_snapshot_fk = foreign_key_name(
        "conversation_citations", ["fleet_snapshot_id"]
    )
    if fleet_snapshot_fk:
        op.drop_constraint(
            fleet_snapshot_fk,
            "conversation_citations",
            type_="foreignkey",
        )
    op.drop_constraint(
        "ck_conversation_citations_source_target",
        "conversation_citations",
        type_="check",
    )
    op.drop_constraint(
        "ck_conversation_citations_source_type",
        "conversation_citations",
        type_="check",
    )
    op.execute("DELETE FROM conversation_citations WHERE source_type = 'fleet_snapshot'")
    op.drop_column("conversation_citations", "fleet_snapshot_id")
    op.create_check_constraint(
        "ck_conversation_citations_source_type",
        "conversation_citations",
        OLD_SOURCE_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_conversation_citations_source_target",
        "conversation_citations",
        source_target_check(include_fleet=False),
    )
    op.drop_index(
        "ix_fleet_conversation_snapshots_turn_id",
        table_name="fleet_conversation_snapshots",
    )
    op.drop_index(
        "ix_fleet_conversation_snapshots_organization_id",
        table_name="fleet_conversation_snapshots",
    )
    op.drop_table("fleet_conversation_snapshots")
    op.drop_index(
        "uq_conversation_sessions_organization_fleet",
        table_name="conversation_sessions",
    )
    op.drop_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        OLD_SESSION_SCOPE_CHECK,
    )
