"""M5.7 non-executable Runbook drafts."""

import sqlalchemy as sa
from alembic import context, op

revision = "0017_m5_runbook_drafts"
down_revision = "0016_m5_conversation_feedback"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    offline = context.is_offline_mode()
    if not offline and has_table("runbook_drafts"):
        return
    op.create_table(
        "runbook_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("source_turn_id", sa.String(length=36), nullable=True),
        sa.Column("source_turn_organization_id", sa.String(length=64), nullable=True),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("source_event_organization_id", sa.String(length=64), nullable=True),
        sa.Column("service_id", sa.String(length=36), nullable=True),
        sa.Column("service_organization_id", sa.String(length=64), nullable=True),
        sa.Column("client_request_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_citation_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status = 'draft'", name="ck_runbook_drafts_status"),
        sa.CheckConstraint(
            "(source_turn_id IS NULL AND source_turn_organization_id IS NULL) OR "
            "(source_turn_id IS NOT NULL AND source_turn_organization_id = organization_id)",
            name="ck_runbook_drafts_turn_scope",
        ),
        sa.CheckConstraint(
            "(source_event_id IS NULL AND source_event_organization_id IS NULL) OR "
            "(source_event_id IS NOT NULL AND source_event_organization_id = organization_id)",
            name="ck_runbook_drafts_event_scope",
        ),
        sa.CheckConstraint(
            "(service_id IS NULL AND service_organization_id IS NULL) OR "
            "(service_id IS NOT NULL AND service_organization_id = organization_id)",
            name="ck_runbook_drafts_service_scope",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "service_organization_id"],
            ["managed_services.id", "managed_services.organization_id"],
            name="fk_runbook_drafts_service_organization",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id", "source_event_organization_id"],
            ["alert_events.id", "alert_events.organization_id"],
            name="fk_runbook_drafts_event_organization",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_turn_id", "source_turn_organization_id"],
            ["conversation_turns.id", "conversation_turns.organization_id"],
            name="fk_runbook_drafts_turn_organization",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "source_turn_id",
            "client_request_id",
            name="uq_runbook_drafts_source_request",
        ),
    )
    for column in (
        "organization_id",
        "source_turn_id",
        "source_event_id",
        "service_id",
    ):
        op.create_index(
            f"ix_runbook_drafts_{column}", "runbook_drafts", [column]
        )


def downgrade() -> None:
    if not has_table("runbook_drafts"):
        return
    for column in (
        "service_id",
        "source_event_id",
        "source_turn_id",
        "organization_id",
    ):
        op.drop_index(
            f"ix_runbook_drafts_{column}", table_name="runbook_drafts"
        )
    op.drop_table("runbook_drafts")
