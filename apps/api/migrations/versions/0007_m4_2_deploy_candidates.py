"""M4.2a read-only deployment candidates."""

import sqlalchemy as sa
from alembic import context, op

revision = "0007_m4_2_deploy_candidates"
down_revision = "0006_m4_safe_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table(
        "agent_deployment_candidates"
    ):
        return
    op.create_table(
        "agent_deployment_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("service_kind", sa.String(length=32), nullable=False),
        sa.Column("service_key", sa.String(length=255), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=True),
        sa.Column("current_digest", sa.String(length=512), nullable=True),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "service_kind", "service_key"),
    )
    op.create_index(
        op.f("ix_agent_deployment_candidates_agent_id"),
        "agent_deployment_candidates",
        ["agent_id"],
    )
    op.create_index(
        op.f("ix_agent_deployment_candidates_observed_at"),
        "agent_deployment_candidates",
        ["observed_at"],
    )


def downgrade() -> None:
    if context.is_offline_mode() or sa.inspect(op.get_bind()).has_table(
        "agent_deployment_candidates"
    ):
        op.drop_table("agent_deployment_candidates")
