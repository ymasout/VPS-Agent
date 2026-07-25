"""M5 contextual read-only Agent and service conversations."""

import sqlalchemy as sa
from alembic import context, op

revision = "0014_m5_context_scope"
down_revision = "0013_m5_repository_scope"
branch_labels = None
depends_on = None


SESSION_SCOPE_CHECK = (
    "("
    "(scope_type = 'event' AND event_id IS NOT NULL "
    "AND repository_id IS NULL AND agent_id IS NULL AND service_id IS NULL) OR "
    "(scope_type = 'repository' AND event_id IS NULL "
    "AND repository_id IS NOT NULL AND agent_id IS NULL AND service_id IS NULL) OR "
    "(scope_type = 'agent' AND event_id IS NULL "
    "AND repository_id IS NULL AND agent_id IS NOT NULL AND service_id IS NULL) OR "
    "(scope_type = 'service' AND event_id IS NULL "
    "AND repository_id IS NULL AND agent_id IS NULL AND service_id IS NOT NULL)"
    ")"
)


def inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in inspector().get_columns(table_name)
    )


def has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspector().get_indexes(table_name)
    )


def has_constraint(table_name: str, constraint_name: str) -> bool:
    constraints = [
        *inspector().get_foreign_keys(table_name),
        *inspector().get_unique_constraints(table_name),
        *inspector().get_check_constraints(table_name),
    ]
    return any(item.get("name") == constraint_name for item in constraints)


def add_unique(table_name: str, name: str, columns: list[str]) -> None:
    if context.is_offline_mode() or not has_constraint(table_name, name):
        op.create_unique_constraint(name, table_name, columns)


def upgrade() -> None:
    offline = context.is_offline_mode()
    add_unique(
        "agents",
        "uq_agents_id_organization_id",
        ["id", "organization_id"],
    )
    add_unique(
        "managed_services",
        "uq_managed_services_id_organization_id",
        ["id", "organization_id"],
    )
    for column_name in ("agent_id", "service_id"):
        if offline or not has_column("conversation_sessions", column_name):
            op.add_column(
                "conversation_sessions",
                sa.Column(column_name, sa.String(length=36), nullable=True),
            )
        index_name = f"ix_conversation_sessions_{column_name}"
        if offline or not has_index("conversation_sessions", index_name):
            op.create_index(
                index_name,
                "conversation_sessions",
                [column_name],
            )
    if offline or has_constraint(
        "conversation_sessions", "ck_conversation_sessions_scope_target"
    ):
        op.drop_constraint(
            "ck_conversation_sessions_scope_target",
            "conversation_sessions",
            type_="check",
        )
    for name, columns in (
        (
            "uq_conversation_sessions_organization_agent",
            ["organization_id", "agent_id"],
        ),
        (
            "uq_conversation_sessions_organization_service",
            ["organization_id", "service_id"],
        ),
    ):
        add_unique("conversation_sessions", name, columns)
    if offline or not has_constraint(
        "conversation_sessions", "fk_conversation_sessions_agent_organization"
    ):
        op.create_foreign_key(
            "fk_conversation_sessions_agent_organization",
            "conversation_sessions",
            "agents",
            ["agent_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="CASCADE",
        )
    if offline or not has_constraint(
        "conversation_sessions", "fk_conversation_sessions_service_organization"
    ):
        op.create_foreign_key(
            "fk_conversation_sessions_service_organization",
            "conversation_sessions",
            "managed_services",
            ["service_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="CASCADE",
        )
    op.create_check_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        SESSION_SCOPE_CHECK,
    )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if not offline:
        scoped_sessions = op.get_bind().execute(
            sa.text(
                "SELECT count(*) FROM conversation_sessions "
                "WHERE scope_type IN ('agent', 'service') "
                "OR agent_id IS NOT NULL OR service_id IS NOT NULL"
            )
        ).scalar_one()
        if scoped_sessions:
            raise RuntimeError(
                "cannot downgrade while Agent or service conversations exist"
            )
    op.drop_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        type_="check",
    )
    for name in (
        "fk_conversation_sessions_service_organization",
        "fk_conversation_sessions_agent_organization",
    ):
        if offline or has_constraint("conversation_sessions", name):
            op.drop_constraint(name, "conversation_sessions", type_="foreignkey")
    for name in (
        "uq_conversation_sessions_organization_service",
        "uq_conversation_sessions_organization_agent",
    ):
        if offline or has_constraint("conversation_sessions", name):
            op.drop_constraint(name, "conversation_sessions", type_="unique")
    for column_name in ("service_id", "agent_id"):
        index_name = f"ix_conversation_sessions_{column_name}"
        if offline or has_index("conversation_sessions", index_name):
            op.drop_index(index_name, table_name="conversation_sessions")
        if offline or has_column("conversation_sessions", column_name):
            op.drop_column("conversation_sessions", column_name)
    op.create_check_constraint(
        "ck_conversation_sessions_scope_target",
        "conversation_sessions",
        "("
        "(scope_type = 'event' AND event_id IS NOT NULL AND repository_id IS NULL) OR "
        "(scope_type = 'repository' AND event_id IS NULL AND repository_id IS NOT NULL)"
        ")",
    )
    for table_name, name in (
        ("managed_services", "uq_managed_services_id_organization_id"),
        ("agents", "uq_agents_id_organization_id"),
    ):
        if offline or has_constraint(table_name, name):
            op.drop_constraint(name, table_name, type_="unique")
