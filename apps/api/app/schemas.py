from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class AgentReport(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    collected_at: datetime
    metrics: Metrics
    services: list[ServiceReport] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def validate_unique_services(self) -> "AgentReport":
        identities = [(service.kind, service.key) for service in self.services]
        if len(identities) != len(set(identities)):
            raise ValueError("service kind and key must be unique within a report")
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
