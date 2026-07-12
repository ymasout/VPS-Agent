import pytest
from pydantic import ValidationError

from app.schemas import Metrics, RegistrationTokenCreate


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
