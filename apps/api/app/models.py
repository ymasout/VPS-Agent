import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    machine_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    os: Mapped[str] = mapped_column(String(128))
    arch: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    metrics: Mapped[list["MetricSnapshot"]] = relationship(cascade="all, delete-orphan")
    services: Mapped[list["ServiceStatus"]] = relationship(cascade="all, delete-orphan")
    evidence_sources: Mapped[list["AgentEvidenceSource"]] = relationship(
        cascade="all, delete-orphan"
    )


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    memory_used_bytes: Mapped[float] = mapped_column(Float)
    memory_total_bytes: Mapped[float] = mapped_column(Float)
    disks: Mapped[list[dict]] = mapped_column(JSON, default=list)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ServiceStatus(Base):
    __tablename__ = "service_statuses"
    __table_args__ = (UniqueConstraint("agent_id", "kind", "service_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    service_key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    healthy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentEvidenceSource(Base):
    """Agent 主动声明的本地只读白名单；控制平面永远不保存执行目标。"""

    __tablename__ = "agent_evidence_sources"
    __table_args__ = (UniqueConstraint("agent_id", "source_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ManagedService(Base):
    __tablename__ = "managed_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    name: Mapped[str] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(64), default="production")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ServiceInstance(Base):
    __tablename__ = "service_instances"
    __table_args__ = (UniqueConstraint("agent_id", "service_kind", "service_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id: Mapped[str] = mapped_column(
        ForeignKey("managed_services.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    service_kind: Mapped[str] = mapped_column(String(32))
    service_key: Mapped[str] = mapped_column(String(255))
    deployment_directory: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeploymentVersion(Base):
    __tablename__ = "deployment_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("service_instances.id", ondelete="CASCADE"), index=True
    )
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstanceLogSource(Base):
    __tablename__ = "instance_log_sources"
    __table_args__ = (UniqueConstraint("instance_id", "source_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("service_instances.id", ondelete="CASCADE"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    active_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="service")
    service_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(32), default="critical")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    observation_count: Mapped[int] = mapped_column(Integer, default=1)
    notification_sequence: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    firing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    silenced_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("event_id", "sequence", "channel"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(32))
    sequence: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(32), default="dingtalk")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE"), index=True
    )
    instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_instances.id", ondelete="SET NULL"), nullable=True
    )
    active_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    provider: Mapped[str] = mapped_column(String(64), default="deterministic")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceRequest(Base):
    __tablename__ = "evidence_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    diagnostic_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_runs.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    log_source_id: Mapped[str] = mapped_column(
        ForeignKey("instance_log_sources.id", ondelete="CASCADE")
    )
    source_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    since_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    until_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_lines: Mapped[int] = mapped_column(Integer)
    max_bytes: Mapped[int] = mapped_column(Integer)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    diagnostic_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_runs.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_requests.id", ondelete="SET NULL"), nullable=True
    )
    evidence_type: Mapped[str] = mapped_column(String(32))
    source_label: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    redacted: Mapped[bool] = mapped_column(Boolean, default=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class DiagnosticCitation(Base):
    __tablename__ = "diagnostic_citations"
    __table_args__ = (UniqueConstraint("diagnostic_id", "section", "item_index", "evidence_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    diagnostic_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_runs.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(32))
    item_index: Mapped[int] = mapped_column(Integer)
