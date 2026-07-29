"""M6.3c/d multi-channel delivery templates and frozen context."""

import sqlalchemy as sa
from alembic import context, op

revision = "0019_m6_multichannel_notifications"
down_revision = "0018_m6_notification_tests"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def upgrade() -> None:
    offline = context.is_offline_mode()
    op.drop_constraint(
        "ck_notification_test_channel",
        "notification_test_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_test_channel",
        "notification_test_requests",
        "channel IN ('dingtalk', 'telegram')",
    )
    if offline or not has_column("alert_events", "notification_channels"):
        op.add_column(
            "alert_events",
            sa.Column("notification_channels", sa.JSON(), nullable=True),
        )
    op.execute(
        "UPDATE alert_events SET notification_channels = json_build_array('dingtalk') "
        "WHERE notification_channels IS NULL"
    )
    op.alter_column("alert_events", "notification_channels", nullable=False)
    if offline or not has_column("notification_deliveries", "template_key"):
        op.add_column(
            "notification_deliveries",
            sa.Column("template_key", sa.String(length=64), nullable=True),
        )
    if offline or not has_column("notification_deliveries", "template_version"):
        op.add_column(
            "notification_deliveries",
            sa.Column("template_version", sa.String(length=32), nullable=True),
        )
    if offline or not has_column("notification_deliveries", "render_context"):
        op.add_column(
            "notification_deliveries",
            sa.Column("render_context", sa.JSON(), nullable=True),
        )
    op.execute(
        """
        UPDATE notification_deliveries AS delivery
        SET template_key = CASE
                WHEN event.source = 'agent' THEN 'agent_' || delivery.notification_type
                ELSE 'service_' || delivery.notification_type
            END,
            template_version = 'v1',
            render_context = json_build_object(
                'title', event.title,
                'detail', COALESCE(event.detail, '无额外详情'),
                'source', event.source,
                'agent_id', event.agent_id,
                'service_kind', event.service_kind,
                'service_key', event.service_key
            )
        FROM alert_events AS event
        WHERE delivery.event_id = event.id
          AND (delivery.template_key IS NULL
            OR delivery.template_version IS NULL
            OR delivery.render_context IS NULL)
        """
    )
    op.alter_column("notification_deliveries", "template_key", nullable=False)
    op.alter_column("notification_deliveries", "template_version", nullable=False)
    op.alter_column("notification_deliveries", "render_context", nullable=False)


def downgrade() -> None:
    offline = context.is_offline_mode()
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM notification_test_requests WHERE channel <> 'dingtalk'
            ) THEN
                RAISE EXCEPTION 'm6 downgrade blocked: non-dingtalk test audit exists';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM notification_deliveries
                WHERE channel <> 'dingtalk' AND status <> 'sent'
            ) THEN
                RAISE EXCEPTION 'm6 downgrade blocked: unfinished non-dingtalk delivery';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM alert_events
                WHERE status IN ('pending', 'firing', 'acknowledged', 'silenced')
                  AND notification_channels::jsonb <> '["dingtalk"]'::jsonb
            ) THEN
                RAISE EXCEPTION 'm6 downgrade blocked: active multi-channel alert';
            END IF;
        END $$
        """
    )
    op.drop_constraint(
        "ck_notification_test_channel",
        "notification_test_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_test_channel",
        "notification_test_requests",
        "channel = 'dingtalk'",
    )
    if offline or has_column("alert_events", "notification_channels"):
        op.drop_column("alert_events", "notification_channels")
    if offline or has_column("notification_deliveries", "render_context"):
        op.drop_column("notification_deliveries", "render_context")
    if offline or has_column("notification_deliveries", "template_version"):
        op.drop_column("notification_deliveries", "template_version")
    if offline or has_column("notification_deliveries", "template_key"):
        op.drop_column("notification_deliveries", "template_key")
