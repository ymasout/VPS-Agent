"""M2 alert events and notification outbox."""

from alembic import op

revision = "0002_m2_alerts"
down_revision = "0001_m1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import AlertEvent, NotificationDelivery

    bind = op.get_bind()
    AlertEvent.__table__.create(bind=bind, checkfirst=True)
    NotificationDelivery.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    from app.models import AlertEvent, NotificationDelivery

    bind = op.get_bind()
    NotificationDelivery.__table__.drop(bind=bind, checkfirst=True)
    AlertEvent.__table__.drop(bind=bind, checkfirst=True)
