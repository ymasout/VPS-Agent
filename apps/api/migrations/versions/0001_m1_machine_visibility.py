"""M1 machine visibility tables."""

from alembic import op

revision = "0001_m1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Models remain the canonical definition; create_all makes fresh self-hosted
    # installs resilient while this migration records the schema baseline.
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
