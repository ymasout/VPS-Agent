from datetime import datetime

from pydantic import BaseModel, Field


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


class Metrics(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    memory_used_bytes: float = Field(ge=0)
    memory_total_bytes: float = Field(ge=0)
    disks: list[DiskMetric] = Field(default_factory=list, max_length=128)


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


class AgentDetail(AgentSummary):
    capabilities: list[str]
    services: list[ServiceView]
