"""M6.4c named approval actor snapshot schema."""

import sqlalchemy as sa
from alembic import context, op

revision = "0020_m6_named_approval"
down_revision = "0019_m6_multichannel_notify"
branch_labels = None
depends_on = None


def has_column(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_column("operations", "requested_principal_snapshot"):
        op.add_column(
            "operations",
            sa.Column("requested_principal_snapshot", sa.JSON(), nullable=True),
        )
    if offline or not has_column("operations", "confirmed_principal_snapshot"):
        op.add_column(
            "operations",
            sa.Column("confirmed_principal_snapshot", sa.JSON(), nullable=True),
        )
    if offline or not has_column("operations", "authorization_mode"):
        op.add_column(
            "operations",
            sa.Column(
                "authorization_mode",
                sa.String(length=32),
                nullable=False,
                server_default="legacy",
            ),
        )
    if offline or not has_column("operation_transitions", "actor_principal_snapshot"):
        op.add_column(
            "operation_transitions",
            sa.Column("actor_principal_snapshot", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    offline = context.is_offline_mode()
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM operations
                WHERE requested_principal_snapshot IS NOT NULL
                   OR confirmed_principal_snapshot IS NOT NULL
                   OR authorization_mode <> 'legacy'
            ) OR EXISTS (
                SELECT 1 FROM operation_transitions
                WHERE actor_principal_snapshot IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'm6 downgrade blocked: named approval audit exists';
            END IF;
        END $$
        """
    )
    if offline or has_column("operation_transitions", "actor_principal_snapshot"):
        op.drop_column("operation_transitions", "actor_principal_snapshot")
    if offline or has_column("operations", "authorization_mode"):
        op.drop_column("operations", "authorization_mode")
    if offline or has_column("operations", "confirmed_principal_snapshot"):
        op.drop_column("operations", "confirmed_principal_snapshot")
    if offline or has_column("operations", "requested_principal_snapshot"):
        op.drop_column("operations", "requested_principal_snapshot")
