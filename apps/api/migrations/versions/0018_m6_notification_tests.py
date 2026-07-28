"""M6.3b audited notification test requests."""

import sqlalchemy as sa
from alembic import context, op

revision = "0018_m6_notification_tests"
down_revision = "0017_m5_runbook_drafts"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    offline = context.is_offline_mode()
    if not offline and has_table("notification_test_requests"):
        return
    op.create_table(
        "notification_test_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("client_request_id", sa.String(length=36), nullable=False),
        sa.Column("rate_limit_window", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel = 'dingtalk'", name="ck_notification_test_channel"),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'succeeded', 'failed', 'delivery_outcome_unknown')",
            name="ck_notification_test_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 1",
            name="ck_notification_test_attempt_count",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "channel",
            "client_request_id",
            name="uq_notification_test_request_idempotency",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "channel",
            "rate_limit_window",
            name="uq_notification_test_rate_window",
        ),
    )
    op.create_index(
        "ix_notification_test_requests_organization_id",
        "notification_test_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_notification_test_requests_status",
        "notification_test_requests",
        ["status"],
    )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if not offline and not has_table("notification_test_requests"):
        return
    op.drop_index(
        "ix_notification_test_requests_status",
        table_name="notification_test_requests",
    )
    op.drop_index(
        "ix_notification_test_requests_organization_id",
        table_name="notification_test_requests",
    )
    op.drop_table("notification_test_requests")
