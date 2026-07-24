import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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


class AgentEvidenceSourceBinding(Base):
    """自动发现来源与稳定服务身份的关联，不包含本地采集目标。"""

    __tablename__ = "agent_evidence_source_bindings"
    __table_args__ = (UniqueConstraint("evidence_source_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evidence_source_id: Mapped[str] = mapped_column(
        ForeignKey("agent_evidence_sources.id", ondelete="CASCADE"), index=True
    )
    service_kind: Mapped[str] = mapped_column(String(32))
    service_key: Mapped[str] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentOperationCapability(Base):
    """Agent 本地明确授权的写能力目录；不包含容器目标。"""

    __tablename__ = "agent_operation_capabilities"
    __table_args__ = (UniqueConstraint("agent_id", "action_type", "service_kind", "service_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    service_kind: Mapped[str] = mapped_column(String(32))
    service_key: Mapped[str] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentDeploymentCandidate(Base):
    """Read-only Compose deployment discovery; never an executable capability."""

    __tablename__ = "agent_deployment_candidates"
    __table_args__ = (UniqueConstraint("agent_id", "service_kind", "service_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    service_kind: Mapped[str] = mapped_column(String(32))
    service_key: Mapped[str] = mapped_column(String(255))
    repository: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_digest: Mapped[str | None] = mapped_column(String(512), nullable=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ManagedService(Base):
    __tablename__ = "managed_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    name: Mapped[str] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(64), default="production")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    criticality: Mapped[str] = mapped_column(String(32), default="critical")
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
    restart_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deploy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_repositories_id_organization_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubRepositoryBinding(Base):
    """控制平面 GitHub App 授权的仓库元数据，不保存安装令牌。"""

    __tablename__ = "github_repository_bindings"
    __table_args__ = (
        UniqueConstraint("repository_id"),
        UniqueConstraint("github_repository_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, index=True)
    github_repository_id: Mapped[int] = mapped_column(BigInteger)
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synchronized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)


class GitHubRepositoryFile(Base):
    """白名单仓库文件的有界脱敏快照。"""

    __tablename__ = "github_repository_files"
    __table_args__ = (UniqueConstraint("repository_id", "commit_sha", "path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    redacted: Mapped[bool] = mapped_column(Boolean, default=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubWebhookDelivery(Base):
    """GitHub App Webhook 的最小审计记录，不持久化原始载荷。"""

    __tablename__ = "github_webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    delivery_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_alert_events_id_organization_id",
        ),
    )

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


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "conversation_request_id",
            name="uq_operations_organization_conversation_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("service_instances.id", ondelete="RESTRICT"), index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_diagnostic_id: Mapped[str | None] = mapped_column(
        ForeignKey("diagnostic_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_conversation_turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    active_key: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(128))
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(32), default="medium")
    impact_summary: Mapped[str] = mapped_column(String(512))
    plan_snapshot: Mapped[dict] = mapped_column(JSON)
    precheck_result: Mapped[dict] = mapped_column(JSON)
    verification_policy: Mapped[dict] = mapped_column(JSON)
    verification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    task_nonce: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_digest: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_digest: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rollback_of: Mapped[str | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OperationTransition(Base):
    __tablename__ = "operation_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        CheckConstraint(
            "("
            "(scope_type = 'event' AND event_id IS NOT NULL AND repository_id IS NULL) OR "
            "(scope_type = 'repository' AND event_id IS NULL AND repository_id IS NOT NULL)"
            ")",
            name="ck_conversation_sessions_scope_target",
        ),
        UniqueConstraint(
            "organization_id",
            "event_id",
            name="uq_conversation_sessions_organization_event",
        ),
        UniqueConstraint(
            "organization_id",
            "repository_id",
            name="uq_conversation_sessions_organization_repository",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversation_sessions_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["event_id", "organization_id"],
            ["alert_events.id", "alert_events.organization_id"],
            name="fk_conversation_sessions_event_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["repository_id", "organization_id"],
            ["repositories.id", "repositories.organization_id"],
            name="fk_conversation_sessions_repository_organization",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    scope_type: Mapped[str] = mapped_column(String(32), default="event")
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    repository_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String(128), default="local-admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_conversation_turns_status",
        ),
        UniqueConstraint(
            "session_id",
            "client_request_id",
            name="uq_conversation_turns_session_request",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversation_turns_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["session_id", "organization_id"],
            ["conversation_sessions.id", "conversation_sessions.organization_id"],
            name="fk_conversation_turns_session_organization",
            ondelete="CASCADE",
        ),
        Index(
            "uq_conversation_turns_active_session",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    client_request_id: Mapped[str] = mapped_column(String(36))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    provider: Mapped[str] = mapped_column(String(64), default="deterministic")
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    context_manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationCitation(Base):
    __tablename__ = "conversation_citations"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ("
            "'alert_event', 'diagnostic_run', 'evidence_item', "
            "'agent_summary', 'service_instance_summary', 'operation', "
            "'repository_file')",
            name="ck_conversation_citations_source_type",
        ),
        CheckConstraint(
            "("
            "(source_type = 'alert_event' AND event_id IS NOT NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'diagnostic_run' AND event_id IS NULL "
            "AND diagnostic_id IS NOT NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'evidence_item' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NOT NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'agent_summary' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NOT NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'service_instance_summary' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NOT NULL AND operation_id IS NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'operation' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NOT NULL "
            "AND repository_file_id IS NULL) OR "
            "(source_type = 'repository_file' AND event_id IS NULL "
            "AND diagnostic_id IS NULL AND evidence_id IS NULL AND agent_id IS NULL "
            "AND instance_id IS NULL AND operation_id IS NULL "
            "AND repository_full_name IS NOT NULL AND repository_path IS NOT NULL "
            "AND repository_commit_sha IS NOT NULL "
            "AND repository_deployment_relation IS NOT NULL "
            "AND repository_truncated IS NOT NULL AND repository_stale IS NOT NULL)"
            ")",
            name="ck_conversation_citations_source_target",
        ),
        CheckConstraint(
            "repository_deployment_relation IS NULL OR "
            "repository_deployment_relation IN ('aligned', 'mismatch', 'unknown')",
            name="ck_conversation_citations_repository_relation",
        ),
        CheckConstraint(
            "(source_type = 'repository_file' "
            "AND repository_basis IN ('deployment', 'snapshot')) OR "
            "(source_type <> 'repository_file' AND repository_basis IS NULL)",
            name="ck_conversation_citations_repository_basis",
        ),
        CheckConstraint(
            "repository_basis <> 'snapshot' OR "
            "(repository_deployment_commit_sha IS NULL "
            "AND repository_deployment_relation = 'unknown')",
            name="ck_conversation_citations_snapshot_semantics",
        ),
        UniqueConstraint(
            "turn_id",
            "section",
            "item_index",
            "citation_index",
            name="uq_conversation_citations_position",
        ),
        ForeignKeyConstraint(
            ["turn_id", "organization_id"],
            ["conversation_turns.id", "conversation_turns.organization_id"],
            name="fk_conversation_citations_turn_organization",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    citation_id: Mapped[str] = mapped_column(String(64))
    section: Mapped[str] = mapped_column(String(32))
    item_index: Mapped[int] = mapped_column(Integer)
    citation_index: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32))
    source_label: Mapped[str] = mapped_column(String(255))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    source_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_events.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    diagnostic_id: Mapped[str | None] = mapped_column(
        ForeignKey("diagnostic_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_instances.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    repository_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("github_repository_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    repository_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repository_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repository_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    repository_deployment_commit_sha: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    repository_deployment_relation: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    repository_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    repository_synchronized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    repository_truncated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    repository_stale: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
