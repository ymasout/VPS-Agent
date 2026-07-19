"""M3 GitHub App read-only repository snapshots."""

from alembic import op

revision = "0005_m3_github_readonly"
down_revision = "0004_m3_service_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import (
        GitHubRepositoryBinding,
        GitHubRepositoryFile,
        GitHubWebhookDelivery,
    )

    bind = op.get_bind()
    for table in (GitHubRepositoryBinding, GitHubRepositoryFile, GitHubWebhookDelivery):
        table.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    from app.models import (
        GitHubRepositoryBinding,
        GitHubRepositoryFile,
        GitHubWebhookDelivery,
    )

    bind = op.get_bind()
    for table in (GitHubWebhookDelivery, GitHubRepositoryFile, GitHubRepositoryBinding):
        table.__table__.drop(bind=bind, checkfirst=True)
