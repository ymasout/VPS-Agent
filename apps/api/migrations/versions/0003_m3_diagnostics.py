"""M3 service context and read-only diagnostics."""

from alembic import op

revision = "0003_m3_diagnostics"
down_revision = "0002_m2_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import (
        AgentEvidenceSource,
        DeploymentVersion,
        DiagnosticCitation,
        DiagnosticRun,
        EvidenceItem,
        EvidenceRequest,
        InstanceLogSource,
        ManagedService,
        Repository,
        ServiceInstance,
    )

    bind = op.get_bind()
    for table in (
        AgentEvidenceSource,
        ManagedService,
        ServiceInstance,
        Repository,
        DeploymentVersion,
        InstanceLogSource,
        DiagnosticRun,
        EvidenceRequest,
        EvidenceItem,
        DiagnosticCitation,
    ):
        table.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    from app.models import (
        AgentEvidenceSource,
        DeploymentVersion,
        DiagnosticCitation,
        DiagnosticRun,
        EvidenceItem,
        EvidenceRequest,
        InstanceLogSource,
        ManagedService,
        Repository,
        ServiceInstance,
    )

    bind = op.get_bind()
    for table in (
        DiagnosticCitation,
        EvidenceItem,
        EvidenceRequest,
        DiagnosticRun,
        InstanceLogSource,
        DeploymentVersion,
        Repository,
        ServiceInstance,
        ManagedService,
        AgentEvidenceSource,
    ):
        table.__table__.drop(bind=bind, checkfirst=True)
