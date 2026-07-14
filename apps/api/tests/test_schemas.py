from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import AgentReport, DiskMetric, Metrics, RegistrationTokenCreate


def test_registration_expiration_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RegistrationTokenCreate(expires_in_minutes=0)


def test_metric_percentages_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Metrics(
            cpu_percent=101,
            memory_percent=10,
            memory_used_bytes=1,
            memory_total_bytes=2,
            disks=[],
        )


def test_resource_usage_cannot_exceed_total_capacity() -> None:
    with pytest.raises(ValidationError, match="memory used bytes"):
        Metrics(
            cpu_percent=10,
            memory_percent=50,
            memory_used_bytes=3,
            memory_total_bytes=2,
            disks=[],
        )

    with pytest.raises(ValidationError, match="disk used bytes"):
        DiskMetric(path="/", used_bytes=3, total_bytes=2, used_percent=50)


def test_report_rejects_duplicate_service_identity() -> None:
    payload = {
        "hostname": "vm-01",
        "version": "0.2.4",
        "capabilities": [],
        "collected_at": datetime.now(timezone.utc),
        "metrics": {
            "cpu_percent": 10,
            "memory_percent": 50,
            "memory_used_bytes": 1,
            "memory_total_bytes": 2,
            "disks": [],
        },
        "services": [
            {"kind": "systemd", "key": "api.service", "name": "api", "state": "active"},
            {"kind": "systemd", "key": "api.service", "name": "api", "state": "failed"},
        ],
    }

    with pytest.raises(ValidationError, match="must be unique"):
        AgentReport.model_validate(payload)
