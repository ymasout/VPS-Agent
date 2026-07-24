"""M5.2.2 repository-scoped read-only conversations."""

import sqlalchemy as sa
from alembic import context, op

revision = "0013_m5_repository_scope"
down_revision = "0012_m5_operation_handoff"
branch_labels = None
depends_on = None


SESSION_SCOPE_CHECK = (
    "("
    "(scope_type = 'event' AND event_id IS NOT NULL AND repository_id IS NULL) OR "
    "(scope_type = 'repository' AND event_id IS NULL AND repository_id IS NOT NULL)"
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


def upgrade() -> None:
    offline = context.is_offline_mode()
    if offline or not has_constraint(
        "repositories", "uq_repositories_id_organization_id"
    ):
        op.create_unique_constraint(
            "uq_repositories_id_organization_id",
            "repositories",
            ["id", "organization_id"],
        )

    if offline or not has_column("conversation_sessions", "repository_id"):
        op.add_column(
            "conversation_sessions",
            sa.Column("repository_id", sa.String(length=36), nullable=True),
        )
    if offline or not has_index(
        "conversation_sessions", "ix_conversation_sessions_repository_id"
    ):
        op.create_index(
            "ix_conversation_sessions_repository_id",
            "conversation_sessions",
            ["repository_id"],
        )

    if offline or has_constraint(
        "conversation_sessions", "ck_conversation_sessions_event_scope"
    ):
        op.drop_constraint(
            "ck_conversation_sessions_event_scope",
            "conversation_sessions",
            type_="check",
        )
    op.alter_column(
        "conversation_sessions",
        "event_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
    if offline or not has_constraint(
        "conversation_sessions",
        "uq_conversation_sessions_organization_repository",
    ):
        op.create_unique_constraint(
            "uq_conversation_sessions_organization_repository",
            "conversation_sessions",
            ["organization_id", "repository_id"],
        )
    if offline or not has_constraint(
        "conversation_sessions",
        "fk_conversation_sessions_repository_organization",
    ):
        op.create_foreign_key(
            "fk_conversation_sessions_repository_organization",
            "conversation_sessions",
            "repositories",
            ["repository_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="RESTRICT",
        )
    if offline or not has_constraint(
        "conversation_sessions", "ck_conversation_sessions_scope_target"
    ):
        op.create_check_constraint(
            "ck_conversation_sessions_scope_target",
            "conversation_sessions",
            SESSION_SCOPE_CHECK,
        )

    if offline or not has_column("conversation_citations", "repository_basis"):
        op.add_column(
            "conversation_citations",
            sa.Column("repository_basis", sa.String(length=16), nullable=True),
        )
    op.execute(
        "UPDATE conversation_citations SET repository_basis = 'deployment' "
        "WHERE source_type = 'repository_file' AND repository_basis IS NULL"
    )
    if offline or not has_constraint(
        "conversation_citations", "ck_conversation_citations_repository_basis"
    ):
        op.create_check_constraint(
            "ck_conversation_citations_repository_basis",
            "conversation_citations",
            "(source_type = 'repository_file' "
            "AND repository_basis IN ('deployment', 'snapshot')) OR "
            "(source_type <> 'repository_file' AND repository_basis IS NULL)",
        )
    if offline or not has_constraint(
        "conversation_citations", "ck_conversation_citations_snapshot_semantics"
    ):
        op.create_check_constraint(
            "ck_conversation_citations_snapshot_semantics",
            "conversation_citations",
            "repository_basis <> 'snapshot' OR "
            "(repository_deployment_commit_sha IS NULL "
            "AND repository_deployment_relation = 'unknown')",
        )


def downgrade() -> None:
    offline = context.is_offline_mode()
    if not offline:
        repository_sessions = op.get_bind().execute(
            sa.text(
                "SELECT count(*) FROM conversation_sessions "
                "WHERE scope_type = 'repository' OR repository_id IS NOT NULL"
            )
        ).scalar_one()
        if repository_sessions:
            raise RuntimeError(
                "cannot downgrade while repository conversation sessions exist"
            )

    if offline or has_constraint(
        "conversation_citations", "ck_conversation_citations_snapshot_semantics"
    ):
        op.drop_constraint(
            "ck_conversation_citations_snapshot_semantics",
            "conversation_citations",
            type_="check",
        )
    if offline or has_constraint(
        "conversation_citations", "ck_conversation_citations_repository_basis"
    ):
        op.drop_constraint(
            "ck_conversation_citations_repository_basis",
            "conversation_citations",
            type_="check",
        )
    if offline or has_column("conversation_citations", "repository_basis"):
        op.drop_column("conversation_citations", "repository_basis")

    if offline or has_constraint(
        "conversation_sessions", "ck_conversation_sessions_scope_target"
    ):
        op.drop_constraint(
            "ck_conversation_sessions_scope_target",
            "conversation_sessions",
            type_="check",
        )
    if offline or has_constraint(
        "conversation_sessions",
        "fk_conversation_sessions_repository_organization",
    ):
        op.drop_constraint(
            "fk_conversation_sessions_repository_organization",
            "conversation_sessions",
            type_="foreignkey",
        )
    if offline or has_constraint(
        "conversation_sessions",
        "uq_conversation_sessions_organization_repository",
    ):
        op.drop_constraint(
            "uq_conversation_sessions_organization_repository",
            "conversation_sessions",
            type_="unique",
        )
    if offline or has_index(
        "conversation_sessions", "ix_conversation_sessions_repository_id"
    ):
        op.drop_index(
            "ix_conversation_sessions_repository_id",
            table_name="conversation_sessions",
        )
    if offline or has_column("conversation_sessions", "repository_id"):
        op.drop_column("conversation_sessions", "repository_id")
    op.alter_column(
        "conversation_sessions",
        "event_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_conversation_sessions_event_scope",
        "conversation_sessions",
        "scope_type = 'event'",
    )

    if offline or has_constraint(
        "repositories", "uq_repositories_id_organization_id"
    ):
        op.drop_constraint(
            "uq_repositories_id_organization_id",
            "repositories",
            type_="unique",
        )
