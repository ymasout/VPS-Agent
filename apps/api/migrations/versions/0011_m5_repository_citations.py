"""M5.2 repository citation tombstones."""

import sqlalchemy as sa
from alembic import context, op

revision = "0011_m5_repository_citations"
down_revision = "0010_m5_event_conversation"
branch_labels = None
depends_on = None


SOURCE_TYPE_CHECK = (
    "source_type IN ("
    "'alert_event', 'diagnostic_run', 'evidence_item', "
    "'agent_summary', 'service_instance_summary', 'operation', 'repository_file')"
)

OLD_SOURCE_TYPE_CHECK = (
    "source_type IN ("
    "'alert_event', 'diagnostic_run', 'evidence_item', "
    "'agent_summary', 'service_instance_summary', 'operation')"
)

OLD_SOURCE_TARGET_CHECK = (
    "("
    "(source_type = 'alert_event' AND event_id IS NOT NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL) OR "
    "(source_type = 'diagnostic_run' AND event_id IS NULL "
    "AND diagnostic_id IS NOT NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL) OR "
    "(source_type = 'evidence_item' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NOT NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL) OR "
    "(source_type = 'agent_summary' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NOT NULL "
    "AND instance_id IS NULL AND operation_id IS NULL) OR "
    "(source_type = 'service_instance_summary' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NOT NULL AND operation_id IS NULL) OR "
    "(source_type = 'operation' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NOT NULL)"
    ")"
)

SOURCE_TARGET_CHECK = (
    "("
    "(source_type = 'alert_event' AND event_id IS NOT NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'diagnostic_run' AND event_id IS NULL "
    "AND diagnostic_id IS NOT NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'evidence_item' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NOT NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'agent_summary' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NOT NULL "
    "AND instance_id IS NULL AND operation_id IS NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'service_instance_summary' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NOT NULL AND operation_id IS NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'operation' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NOT NULL "
    "AND repository_file_id IS NULL) OR "
    "(source_type = 'repository_file' AND event_id IS NULL "
    "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
    "AND instance_id IS NULL AND operation_id IS NULL "
    "AND repository_full_name IS NOT NULL AND repository_path IS NOT NULL "
    "AND repository_commit_sha IS NOT NULL "
    "AND repository_deployment_relation IS NOT NULL "
    "AND repository_truncated IS NOT NULL AND repository_stale IS NOT NULL)"
    ")"
)


def has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def has_repository_file_foreign_key() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        foreign_key.get("constrained_columns") == ["repository_file_id"]
        for foreign_key in inspector.get_foreign_keys("conversation_citations")
    )


def has_constraint(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    constraints = [
        *inspector.get_foreign_keys(table_name),
        *inspector.get_check_constraints(table_name),
    ]
    return any(item.get("name") == constraint_name for item in constraints)


def upgrade() -> None:
    offline = context.is_offline_mode()
    columns = (
        sa.Column("repository_file_id", sa.String(length=36), nullable=True),
        sa.Column("repository_full_name", sa.String(length=255), nullable=True),
        sa.Column("repository_path", sa.String(length=512), nullable=True),
        sa.Column("repository_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("repository_deployment_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("repository_deployment_relation", sa.String(length=16), nullable=True),
        sa.Column("repository_synchronized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repository_truncated", sa.Boolean(), nullable=True),
        sa.Column("repository_stale", sa.Boolean(), nullable=True),
    )
    for column in columns:
        if offline or not has_column("conversation_citations", column.name):
            op.add_column("conversation_citations", column)

    if offline or has_constraint("conversation_citations", "ck_conversation_citations_source_type"):
        op.drop_constraint(
            "ck_conversation_citations_source_type",
            "conversation_citations",
            type_="check",
        )
    if offline or has_constraint(
        "conversation_citations", "ck_conversation_citations_source_target"
    ):
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
        SOURCE_TARGET_CHECK,
    )
    if offline or not has_constraint(
        "conversation_citations",
        "ck_conversation_citations_repository_relation",
    ):
        op.create_check_constraint(
            "ck_conversation_citations_repository_relation",
            "conversation_citations",
            "repository_deployment_relation IS NULL OR "
            "repository_deployment_relation IN ('aligned', 'mismatch', 'unknown')",
        )
    if offline or not has_repository_file_foreign_key():
        op.create_foreign_key(
            "fk_conversation_citations_repository_file",
            "conversation_citations",
            "github_repository_files",
            ["repository_file_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if offline or not has_index(
        "conversation_citations",
        "ix_conversation_citations_repository_file_id",
    ):
        op.create_index(
            "ix_conversation_citations_repository_file_id",
            "conversation_citations",
            ["repository_file_id"],
        )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if offline or has_index(
        "conversation_citations",
        "ix_conversation_citations_repository_file_id",
    ):
        op.drop_index(
            "ix_conversation_citations_repository_file_id",
            table_name="conversation_citations",
        )
    if offline or has_constraint(
        "conversation_citations",
        "fk_conversation_citations_repository_file",
    ):
        op.drop_constraint(
            "fk_conversation_citations_repository_file",
            "conversation_citations",
            type_="foreignkey",
        )
    if offline or has_constraint(
        "conversation_citations",
        "ck_conversation_citations_repository_relation",
    ):
        op.drop_constraint(
            "ck_conversation_citations_repository_relation",
            "conversation_citations",
            type_="check",
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
    # Existing repository citations cannot be represented by 0010.
    op.execute("DELETE FROM conversation_citations WHERE source_type = 'repository_file'")
    for name in (
        "repository_stale",
        "repository_truncated",
        "repository_synchronized_at",
        "repository_deployment_relation",
        "repository_deployment_commit_sha",
        "repository_commit_sha",
        "repository_path",
        "repository_full_name",
        "repository_file_id",
    ):
        op.drop_column("conversation_citations", name)
    op.create_check_constraint(
        "ck_conversation_citations_source_type",
        "conversation_citations",
        OLD_SOURCE_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_conversation_citations_source_target",
        "conversation_citations",
        OLD_SOURCE_TARGET_CHECK,
    )
