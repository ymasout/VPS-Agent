"""M4.2c explicit rollback operation linkage."""

import sqlalchemy as sa
from alembic import context, op

revision = "0009_m4_2_rollback"
down_revision = "0008_m4_2_deploy_execute"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def has_index(table_name: str, index_name: str) -> bool:
    return any(
        index.get("name") == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_column("operations", "rollback_of"):
        op.add_column(
            "operations", sa.Column("rollback_of", sa.String(length=36), nullable=True)
        )
    if offline or not has_foreign_key("operations", "fk_operations_rollback_of_operations"):
        op.create_foreign_key(
            "fk_operations_rollback_of_operations",
            "operations",
            "operations",
            ["rollback_of"],
            ["id"],
            ondelete="RESTRICT",
        )
    if offline or not has_index("operations", "ix_operations_rollback_of"):
        op.create_index("ix_operations_rollback_of", "operations", ["rollback_of"])


def downgrade() -> None:
    offline = context.is_offline_mode()
    if offline or has_index("operations", "ix_operations_rollback_of"):
        op.drop_index("ix_operations_rollback_of", table_name="operations")
    if offline or has_foreign_key("operations", "fk_operations_rollback_of_operations"):
        op.drop_constraint(
            "fk_operations_rollback_of_operations", "operations", type_="foreignkey"
        )
    if offline or has_column("operations", "rollback_of"):
        op.drop_column("operations", "rollback_of")
