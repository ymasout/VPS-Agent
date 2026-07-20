from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegistrationTokenCreate(BaseModel):
    name: str = Field(default="VPS Agent", min_length=1, max_length=255)
    expires_in_minutes: int = Field(default=30, ge=1, le=1440)


class RegistrationTokenCreated(BaseModel):
    token: str
    expires_at: datetime


class AgentRegister(BaseModel):
    token: str = Field(min_length=16)
    name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(min_length=1, max_length=255)
    machine_id: str = Field(min_length=1, max_length=255)
    os: str = Field(min_length=1, max_length=128)
    arch: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class AgentRegistered(BaseModel):
    agent_id: str
    credential: str


class DiskMetric(BaseModel):
    path: str = Field(max_length=255)
    used_bytes: float = Field(ge=0)
    total_bytes: float = Field(ge=0)
    used_percent: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_usage(self) -> "DiskMetric":
        if self.used_bytes > self.total_bytes:
            raise ValueError("disk used bytes cannot exceed total bytes")
        return self


class Metrics(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    memory_used_bytes: float = Field(ge=0)
    memory_total_bytes: float = Field(ge=0)
    disks: list[DiskMetric] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_usage(self) -> "Metrics":
        if self.memory_used_bytes > self.memory_total_bytes:
            raise ValueError("memory used bytes cannot exceed total bytes")
        return self


class ServiceReport(BaseModel):
    kind: str = Field(pattern="^(docker|systemd|http)$")
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    state: str = Field(min_length=1, max_length=64)
    detail: str | None = Field(default=None, max_length=512)
    healthy: bool | None = None


class EvidenceSourceReport(BaseModel):
    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    kind: Literal["docker_logs", "systemd_journal"]
    display_name: str = Field(min_length=1, max_length=255)
    service_kind: Literal["docker", "systemd"] | None = None
    service_key: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_service_association(self) -> "EvidenceSourceReport":
        if (self.service_kind is None) != (self.service_key is None):
            raise ValueError("service kind and key must be provided together")
        return self


class OperationCapabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["docker_restart"]
    service_kind: Literal["docker"]
    service_key: str = Field(min_length=1, max_length=255)


class AgentReport(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    collected_at: datetime
    metrics: Metrics
    services: list[ServiceReport] = Field(default_factory=list, max_length=2000)
    evidence_sources: list[EvidenceSourceReport] = Field(default_factory=list, max_length=128)
    operation_capabilities: list[OperationCapabilityReport] = Field(
        default_factory=list, max_length=128
    )

    @model_validator(mode="after")
    def validate_unique_services(self) -> "AgentReport":
        identities = [(service.kind, service.key) for service in self.services]
        if len(identities) != len(set(identities)):
            raise ValueError("service kind and key must be unique within a report")
        source_keys = [source.key for source in self.evidence_sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("evidence source keys must be unique within a report")
        operation_keys = [
            (item.action_type, item.service_kind, item.service_key)
            for item in self.operation_capabilities
        ]
        if len(operation_keys) != len(set(operation_keys)):
            raise ValueError("operation capabilities must be unique within a report")
        return self


class ReportReceipt(BaseModel):
    status: str = "accepted"
    received_at: datetime


class MetricView(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_used_bytes: float
    memory_total_bytes: float
    disks: list[dict]
    collected_at: datetime


class ServiceView(BaseModel):
    kind: str
    key: str
    name: str
    state: str
    detail: str | None
    healthy: bool | None
    observed_at: datetime


class AgentSummary(BaseModel):
    id: str
    name: str
    hostname: str
    os: str
    arch: str
    version: str
    online: bool
    last_seen_at: datetime | None
    latest_metrics: MetricView | None
    service_counts: dict[str, int]
    service_kind_counts: dict[str, int]
    service_problem_count: int


class AgentDetail(AgentSummary):
    capabilities: list[str]
    services: list[ServiceView]


class AlertEventView(BaseModel):
    id: str
    agent_id: str
    source: str
    service_kind: str | None
    service_key: str | None
    title: str
    severity: str
    status: str
    observation_count: int
    detail: str | None
    first_observed_at: datetime
    last_observed_at: datetime
    firing_at: datetime | None
    acknowledged_at: datetime | None
    silenced_until: datetime | None
    resolved_at: datetime | None


class AlertEventAction(BaseModel):
    action: Literal["acknowledge", "silence"]
    silence_minutes: int = Field(default=60, ge=1, le=10080)


class ServiceMappingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    agent_id: str = Field(min_length=1, max_length=36)
    service_kind: Literal["docker", "systemd", "http"]
    service_key: str = Field(min_length=1, max_length=255)
    deployment_directory: str | None = Field(default=None, max_length=512)
    log_source_key: str = Field(min_length=1, max_length=128)
    repository_full_name: str | None = Field(
        default=None, max_length=255, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    image_digest: str | None = Field(default=None, max_length=255)
    criticality: Literal["critical", "non_critical"] = "critical"
    restart_enabled: bool = False

    @field_validator("deployment_directory")
    @classmethod
    def validate_deployment_directory(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if not value.startswith("/") or any(part in {".", ".."} for part in parts):
            raise ValueError("deployment directory must be an absolute normalized Linux path")
        return value


class ServiceMappingView(BaseModel):
    service_id: str
    instance_id: str
    name: str
    environment: str
    agent_id: str
    service_kind: str
    service_key: str
    deployment_directory: str | None
    log_source_key: str
    repository_full_name: str | None
    commit_sha: str | None
    image_digest: str | None
    criticality: str
    restart_enabled: bool


class ServiceMappingCandidate(BaseModel):
    agent_id: str
    service_kind: str
    service_key: str
    service_name: str
    state: str
    healthy: bool | None
    log_source_key: str
    log_source_name: str
    mapped: bool
    instance_id: str | None
    operation_capable: bool = False
    restart_enabled: bool = False
    criticality: str = "critical"


class RestartPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    criticality: Literal["critical", "non_critical"]


class OperationPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str | None = Field(default=None, max_length=36)
    event_id: str | None = Field(default=None, max_length=36)
    diagnostic_id: str | None = Field(default=None, max_length=36)
    action_type: Literal["docker_restart"] = "docker_restart"
    expires_in_seconds: int = Field(default=300, ge=60, le=900)


class OperationConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed_by: str = Field(default="local-admin", min_length=1, max_length=128)


class OperationExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "failed"]
    exit_code: int | None = Field(default=None, ge=-1, le=255)
    output: str = Field(default="", max_length=65536)
    truncated: bool = False
    error_code: str | None = Field(default=None, max_length=64)
    error_detail: str | None = Field(default=None, max_length=512)
    completed_at: datetime


class OperationTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["v1"] = "v1"
    operation_id: str
    action_type: Literal["docker_restart"]
    agent_id: str
    service_kind: Literal["docker"]
    service_key: str
    issued_at: datetime
    expires_at: datetime
    idempotency_key: str
    attempt: int
    nonce: str
    key_id: str
    signature: str


class OperationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: OperationTask | None = None


class OperationTransitionView(BaseModel):
    from_status: str | None
    to_status: str
    actor_type: str
    actor_id: str | None
    reason: str | None
    details: dict
    created_at: datetime


class OperationView(BaseModel):
    id: str
    instance_id: str
    agent_id: str
    source_event_id: str | None
    source_diagnostic_id: str | None
    action_type: str
    status: str
    requested_by: str
    confirmed_by: str | None
    risk_level: str
    impact_summary: str
    plan_snapshot: dict
    precheck_result: dict
    verification_policy: dict
    verification_result: dict | None
    expires_at: datetime
    requested_at: datetime
    confirmed_at: datetime | None
    claimed_at: datetime | None
    started_at: datetime | None
    execution_completed_at: datetime | None
    completed_at: datetime | None
    exit_code: int | None
    output: str | None
    output_truncated: bool
    error_code: str | None
    error_detail: str | None
    transitions: list[OperationTransitionView]


class OperationReceipt(BaseModel):
    operation_id: str
    status: str


class GitHubRepositoryView(BaseModel):
    id: str
    full_name: str
    default_branch: str
    private: bool
    head_sha: str | None
    synchronized_at: datetime | None
    last_error: str | None


class GitHubSyncReceipt(BaseModel):
    status: str = "completed"
    repository_count: int


class GitHubStatusView(BaseModel):
    configured: bool
    app_slug: str | None
    installation_url: str | None
    allowed_file_paths: list[str]
    repository_count: int


class GitHubWebhookReceipt(BaseModel):
    status: str = "accepted"
    duplicate: bool = False


class EvidenceRequestWork(BaseModel):
    id: str
    source_key: str
    since_at: datetime
    until_at: datetime
    max_lines: int
    max_bytes: int
    timeout_seconds: int


class EvidenceRequestClaim(BaseModel):
    request: EvidenceRequestWork | None = None


class EvidenceRequestComplete(BaseModel):
    status: Literal["completed", "failed"]
    content: str = Field(default="", max_length=131072)
    collected_at: datetime
    redacted: bool = True
    truncated: bool = False
    error: str | None = Field(default=None, max_length=512)


class EvidenceRequestReceipt(BaseModel):
    status: str = "accepted"
    diagnostic_id: str
    diagnostic_status: str


class DiagnosticFact(BaseModel):
    statement: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=16)


class DiagnosticInference(BaseModel):
    statement: str = Field(min_length=1, max_length=1000)
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(min_length=1, max_length=16)


class DiagnosticRecommendation(BaseModel):
    action: str = Field(min_length=1, max_length=1000)
    risk: Literal["low", "medium", "high"]
    requires_confirmation: bool = True
    prerequisites: list[str] = Field(default_factory=list, max_length=16)


class DiagnosticResult(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    facts: list[DiagnosticFact] = Field(default_factory=list, max_length=64)
    inferences: list[DiagnosticInference] = Field(default_factory=list, max_length=64)
    recommendations: list[DiagnosticRecommendation] = Field(default_factory=list, max_length=64)
    missing_evidence: list[str] = Field(default_factory=list, max_length=64)


class EvidenceView(BaseModel):
    id: str
    evidence_type: str
    source_label: str
    content: str
    redacted: bool
    truncated: bool
    collected_at: datetime
    source_metadata: dict


class DiagnosticView(BaseModel):
    id: str
    event_id: str
    instance_id: str | None
    status: str
    trigger: str
    provider: str
    result: DiagnosticResult | None
    error_code: str | None
    error_detail: str | None
    evidence: list[EvidenceView] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
