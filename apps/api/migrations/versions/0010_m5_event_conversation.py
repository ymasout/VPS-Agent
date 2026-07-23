"""M5.1 event-scoped read-only conversation tables."""

import sqlalchemy as sa
from alembic import context, op

revision = "0010_m5_event_conversation"
down_revision = "0009_m4_2_rollback"
branch_labels = None
depends_on = None


def inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table_name: str) -> bool:
    return inspector().has_table(table_name)


def has_unique(table_name: str, constraint_name: str) -> bool:
    return any(
        item.get("name") == constraint_name
        for item in inspector().get_unique_constraints(table_name)
    )


def create_conversation_sessions() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type = 'event'",
            name="ck_conversation_sessions_event_scope",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "organization_id"],
            ["alert_events.id", "alert_events.organization_id"],
            name="fk_conversation_sessions_event_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "event_id",
            name="uq_conversation_sessions_organization_event",
        ),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversation_sessions_id_organization_id",
        ),
    )
    op.create_index(
        "ix_conversation_sessions_event_id",
        "conversation_sessions",
        ["event_id"],
    )
    op.create_index(
        "ix_conversation_sessions_organization_id",
        "conversation_sessions",
        ["organization_id"],
    )


def create_conversation_turns() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("client_request_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("context_manifest", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_conversation_turns_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "organization_id"],
            ["conversation_sessions.id", "conversation_sessions.organization_id"],
            name="fk_conversation_turns_session_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "client_request_id",
            name="uq_conversation_turns_session_request",
        ),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversation_turns_id_organization_id",
        ),
    )
    op.create_index(
        "ix_conversation_turns_organization_id",
        "conversation_turns",
        ["organization_id"],
    )
    op.create_index(
        "ix_conversation_turns_session_id",
        "conversation_turns",
        ["session_id"],
    )
    op.create_index(
        "ix_conversation_turns_status",
        "conversation_turns",
        ["status"],
    )
    op.create_index(
        "uq_conversation_turns_active_session",
        "conversation_turns",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def create_conversation_citations() -> None:
    op.create_table(
        "conversation_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("citation_id", sa.String(length=64), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=True),
        sa.Column("diagnostic_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("instance_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "source_type IN ("
            "'alert_event', 'diagnostic_run', 'evidence_item', "
            "'agent_summary', 'service_instance_summary', 'operation')",
            name="ck_conversation_citations_source_type",
        ),
        sa.CheckConstraint(
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
            ")",
            name="ck_conversation_citations_source_target",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "organization_id"],
            ["conversation_turns.id", "conversation_turns.organization_id"],
            name="fk_conversation_citations_turn_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["diagnostic_id"], ["diagnostic_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instance_id"], ["service_instances.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "section",
            "item_index",
            "citation_index",
            name="uq_conversation_citations_position",
        ),
    )
    for column in (
        "agent_id",
        "diagnostic_id",
        "event_id",
        "evidence_id",
        "instance_id",
        "operation_id",
        "organization_id",
        "turn_id",
    ):
        op.create_index(
            f"ix_conversation_citations_{column}",
            "conversation_citations",
            [column],
        )


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_unique("alert_events", "uq_alert_events_id_organization_id"):
        op.create_unique_constraint(
            "uq_alert_events_id_organization_id",
            "alert_events",
            ["id", "organization_id"],
        )
    if offline or not has_table("conversation_sessions"):
        create_conversation_sessions()
    if offline or not has_table("conversation_turns"):
        create_conversation_turns()
    if offline or not has_table("conversation_citations"):
        create_conversation_citations()


def downgrade() -> None:
    offline = context.is_offline_mode()
    for table_name in (
        "conversation_citations",
        "conversation_turns",
        "conversation_sessions",
    ):
        if offline or has_table(table_name):
            op.drop_table(table_name)
    if offline or has_unique("alert_events", "uq_alert_events_id_organization_id"):
        op.drop_constraint(
            "uq_alert_events_id_organization_id",
            "alert_events",
            type_="unique",
        )
