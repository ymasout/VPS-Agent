"""M4.2b controlled Compose deployment execution."""

import sqlalchemy as sa
from alembic import context, op

revision = "0008_m4_2_deploy_execute"
down_revision = "0007_m4_2_deploy_candidates"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_column("service_instances", "deploy_enabled"):
        op.add_column(
            "service_instances",
            sa.Column("deploy_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if offline or not has_column("operations", "current_digest"):
        op.add_column(
            "operations", sa.Column("current_digest", sa.String(length=512), nullable=True)
        )
    if offline or not has_column("operations", "target_digest"):
        op.add_column(
            "operations", sa.Column("target_digest", sa.String(length=512), nullable=True)
        )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if offline or has_column("operations", "target_digest"):
        op.drop_column("operations", "target_digest")
    if offline or has_column("operations", "current_digest"):
        op.drop_column("operations", "current_digest")
    if offline or has_column("service_instances", "deploy_enabled"):
        op.drop_column("service_instances", "deploy_enabled")
