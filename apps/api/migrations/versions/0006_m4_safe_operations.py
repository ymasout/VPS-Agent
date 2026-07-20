"""M4 signed and auditable Docker restart operations."""

import sqlalchemy as sa
from alembic import op

revision = "0006_m4_safe_operations"
down_revision = "0005_m3_github_readonly"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not has_column("managed_services", "criticality"):
        op.add_column(
            "managed_services",
            sa.Column(
                "criticality",
                sa.String(length=32),
                nullable=False,
                server_default="critical",
            ),
        )
    if not has_column("service_instances", "restart_enabled"):
        op.add_column(
            "service_instances",
            sa.Column("restart_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_operation_capabilities"):
        op.create_table(
            "agent_operation_capabilities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column("service_kind", sa.String(length=32), nullable=False),
            sa.Column("service_key", sa.String(length=255), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agent_id", "action_type", "service_kind", "service_key"),
        )
        op.create_index(
            op.f("ix_agent_operation_capabilities_agent_id"),
            "agent_operation_capabilities",
            ["agent_id"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("operations"):
        op.create_table(
            "operations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("instance_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("source_event_id", sa.String(length=36), nullable=True),
            sa.Column("source_diagnostic_id", sa.String(length=36), nullable=True),
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("active_key", sa.String(length=320), nullable=True),
            sa.Column("requested_by", sa.String(length=128), nullable=False),
            sa.Column("confirmed_by", sa.String(length=128), nullable=True),
            sa.Column("risk_level", sa.String(length=32), nullable=False),
            sa.Column("impact_summary", sa.String(length=512), nullable=False),
            sa.Column("plan_snapshot", sa.JSON(), nullable=False),
            sa.Column("precheck_result", sa.JSON(), nullable=False),
            sa.Column("verification_policy", sa.JSON(), nullable=False),
            sa.Column("verification_result", sa.JSON(), nullable=True),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("task_nonce", sa.String(length=128), nullable=True),
            sa.Column("signing_key_id", sa.String(length=64), nullable=True),
            sa.Column("task_signature", sa.String(length=256), nullable=True),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("execution_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("output", sa.Text(), nullable=True),
            sa.Column("output_truncated", sa.Boolean(), nullable=False),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_detail", sa.String(length=512), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["instance_id"], ["service_instances.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["source_diagnostic_id"], ["diagnostic_runs.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["source_event_id"], ["alert_events.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("active_key"),
            sa.UniqueConstraint("idempotency_key"),
            sa.UniqueConstraint("task_nonce"),
        )
        for column in (
            "agent_id",
            "expires_at",
            "instance_id",
            "organization_id",
            "source_diagnostic_id",
            "source_event_id",
            "status",
        ):
            op.create_index(op.f(f"ix_operations_{column}"), "operations", [column])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("operation_transitions"):
        op.create_table(
            "operation_transitions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("operation_id", sa.String(length=36), nullable=False),
            sa.Column("from_status", sa.String(length=32), nullable=True),
            sa.Column("to_status", sa.String(length=32), nullable=False),
            sa.Column("actor_type", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.String(length=128), nullable=True),
            sa.Column("reason", sa.String(length=512), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_operation_transitions_operation_id"),
            "operation_transitions",
            ["operation_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in (
        "operation_transitions",
        "operations",
        "agent_operation_capabilities",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
            inspector = sa.inspect(op.get_bind())
    if has_column("service_instances", "restart_enabled"):
        op.drop_column("service_instances", "restart_enabled")
    if has_column("managed_services", "criticality"):
        op.drop_column("managed_services", "criticality")
