"""M5.6 explicit conversation feedback."""

import sqlalchemy as sa
from alembic import context, op

revision = "0016_m5_conversation_feedback"
down_revision = "0015_m5_fleet_conversation"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    offline = context.is_offline_mode()
    if not offline and has_table("conversation_turn_feedback"):
        return
    op.create_table(
        "conversation_turn_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating IN ('helpful', 'not_helpful')",
            name="ck_conversation_turn_feedback_rating",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN "
            "('incorrect', 'missing_context', 'unclear', 'unsafe_suggestion', 'other')",
            name="ck_conversation_turn_feedback_reason",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "organization_id"],
            ["conversation_turns.id", "conversation_turns.organization_id"],
            name="fk_conversation_turn_feedback_turn_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "turn_id",
            "created_by",
            name="uq_conversation_turn_feedback_actor",
        ),
    )
    op.create_index(
        "ix_conversation_turn_feedback_organization_id",
        "conversation_turn_feedback",
        ["organization_id"],
    )
    op.create_index(
        "ix_conversation_turn_feedback_turn_id",
        "conversation_turn_feedback",
        ["turn_id"],
    )


def downgrade() -> None:
    if not has_table("conversation_turn_feedback"):
        return
    op.drop_index(
        "ix_conversation_turn_feedback_turn_id",
        table_name="conversation_turn_feedback",
    )
    op.drop_index(
        "ix_conversation_turn_feedback_organization_id",
        table_name="conversation_turn_feedback",
    )
    op.drop_table("conversation_turn_feedback")
