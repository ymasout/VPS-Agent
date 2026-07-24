"""M5.3 conversation-to-operation source and request idempotency."""

import sqlalchemy as sa
from alembic import context, op

revision = "0012_m5_operation_handoff"
down_revision = "0011_m5_repository_citations"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def has_constraint(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    constraints = [
        *inspector.get_foreign_keys(table_name),
        *inspector.get_unique_constraints(table_name),
    ]
    return any(item.get("name") == constraint_name for item in constraints)


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_column("operations", "source_conversation_turn_id"):
        op.add_column(
            "operations",
            sa.Column("source_conversation_turn_id", sa.String(length=36), nullable=True),
        )
    if offline or not has_column("operations", "conversation_request_id"):
        op.add_column(
            "operations",
            sa.Column("conversation_request_id", sa.String(length=36), nullable=True),
        )
    if offline or not has_constraint(
        "operations", "fk_operations_source_conversation_turn"
    ):
        op.create_foreign_key(
            "fk_operations_source_conversation_turn",
            "operations",
            "conversation_turns",
            ["source_conversation_turn_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if offline or not has_index(
        "operations", "ix_operations_source_conversation_turn_id"
    ):
        op.create_index(
            "ix_operations_source_conversation_turn_id",
            "operations",
            ["source_conversation_turn_id"],
        )
    if offline or not has_constraint(
        "operations", "uq_operations_organization_conversation_request"
    ):
        op.create_unique_constraint(
            "uq_operations_organization_conversation_request",
            "operations",
            ["organization_id", "conversation_request_id"],
        )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if offline or has_constraint(
        "operations", "uq_operations_organization_conversation_request"
    ):
        op.drop_constraint(
            "uq_operations_organization_conversation_request",
            "operations",
            type_="unique",
        )
    if offline or has_index(
        "operations", "ix_operations_source_conversation_turn_id"
    ):
        op.drop_index(
            "ix_operations_source_conversation_turn_id",
            table_name="operations",
        )
    if offline or has_constraint(
        "operations", "fk_operations_source_conversation_turn"
    ):
        op.drop_constraint(
            "fk_operations_source_conversation_turn",
            "operations",
            type_="foreignkey",
        )
    if offline or has_column("operations", "conversation_request_id"):
        op.drop_column("operations", "conversation_request_id")
    if offline or has_column("operations", "source_conversation_turn_id"):
        op.drop_column("operations", "source_conversation_turn_id")
