"""M3 stable service discovery and evidence source bindings."""

from alembic import op

revision = "0004_m3_service_discovery"
down_revision = "0003_m3_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import AgentEvidenceSourceBinding

    AgentEvidenceSourceBinding.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from app.models import AgentEvidenceSourceBinding

    AgentEvidenceSourceBinding.__table__.drop(bind=op.get_bind(), checkfirst=True)
