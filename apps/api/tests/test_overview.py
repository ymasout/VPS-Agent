import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import Request
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.models import MetricSnapshot, Operation
from app.overview import (
    MAX_RAW_POINTS_PER_AGENT,
    MAX_TREND_POINTS,
    build_trend,
    console_overview,
    disk_percent,
    latest_metrics_query,
    operation_access,
    operation_target,
    resource_tone,
)

TOKEN = "test-only-" + ("x" * 32)
WRITE_TOKEN = "test-write-only-" + ("y" * 32)


def snapshot(at: datetime, *, cpu: float = 10, memory: float = 20, disks=None):
    return MetricSnapshot(
        agent_id="agent-01",
        cpu_percent=cpu,
        memory_percent=memory,
        memory_used_bytes=1,
        memory_total_bytes=2,
        disks=[] if disks is None else disks,
        collected_at=at,
    )


def request_for(user: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/console-overview",
            "headers": [
                (b"x-vps-agent-principal-id", user.encode("ascii")),
                (b"x-vps-agent-principal-source", b"caddy_basic"),
                (b"x-vps-agent-principal-proxy-token", TOKEN.encode("ascii")),
            ],
        }
    )


def enforced_settings() -> Settings:
    return Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_read_authorization_enabled=True,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="viewer,operator",
        principal_write_context_enabled=True,
        principal_write_authorization_enabled=True,
        principal_write_proxy_token=WRITE_TOKEN,
        principal_role_bindings_json=(
            '[{"auth_source":"caddy_basic","auth_subject":"operator",'
            '"principal_id":"local:4bf4ab08-4da6-44bb-8607-3c87f1946012",'
            '"display_name":"Operator","roles":["operator"]},'
            '{"auth_source":"caddy_basic","auth_subject":"approver",'
            '"principal_id":"local:7c09f56b-f777-4277-99d8-8ac55b69b0ff",'
            '"display_name":"Approver","roles":["approver"]}]'
        ),
    )


def test_trend_contract_is_bounded_and_distinguishes_data_states() -> None:
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    complete = [
        snapshot(now - timedelta(minutes=minute), cpu=minute % 100)
        for minute in range(0, 24 * 60 + 1, 4)
    ]
    available = build_trend(
        complete, lambda item: item.cpu_percent, current_time=now, stale_after_seconds=90
    )
    assert available.status == "available"
    assert len(available.points) <= MAX_TREND_POINTS
    assert MAX_RAW_POINTS_PER_AGENT == 1440

    insufficient = build_trend(
        complete[:30], lambda item: item.cpu_percent, current_time=now, stale_after_seconds=90
    )
    assert insufficient.status == "insufficient"

    stale = build_trend(
        [item for item in complete if item.collected_at <= now - timedelta(minutes=10)],
        lambda item: item.cpu_percent,
        current_time=now,
        stale_after_seconds=90,
    )
    assert stale.status == "stale"

    gapped = build_trend(
        [complete[0], complete[-1]],
        lambda item: item.cpu_percent,
        current_time=now,
        stale_after_seconds=90,
    )
    assert gapped.status == "gapped"

    unavailable = build_trend(
        complete,
        disk_percent,
        current_time=now,
        stale_after_seconds=90,
    )
    assert unavailable.status == "unavailable"
    assert unavailable.points == []


def test_disk_and_threshold_semantics_match_frozen_overview() -> None:
    metric = snapshot(
        datetime.now(timezone.utc),
        disks=[
            {"path": "/", "used_percent": 71},
            {"path": "/data", "used_percent": 85},
            {"path": "/ignored"},
        ],
    )
    assert disk_percent(metric) == 85
    assert resource_tone(None) == "neutral"
    assert resource_tone(69.9) == "success"
    assert resource_tone(71) == "warning"
    assert resource_tone(85) == "danger"


def test_latest_metric_query_uses_bounded_lateral_lookup() -> None:
    sql = str(
        latest_metrics_query(["agent-01"]).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "JOIN LATERAL" in sql
    assert "LIMIT 1" in sql
    assert "row_number" not in sql.lower()


def test_operation_summary_obeys_named_read_capability() -> None:
    settings = enforced_settings()
    assert operation_access(request_for("viewer"), settings, None) == (False, False)
    assert operation_access(request_for("operator"), settings, None) == (True, False)
    assert operation_access(request_for("approver"), settings, None) == (True, True)
    assert operation_access(request_for("viewer"), settings, "change-me-in-production") == (
        False,
        False,
    )

    legacy = Settings(skip_database_init=True)
    assert operation_access(request_for("viewer"), legacy, None) == (True, True)


def test_operation_target_only_uses_bounded_display_fields() -> None:
    operation = Operation(
        id="op-01",
        instance_id="instance-01",
        agent_id="agent-01",
        action_type="docker_restart",
        status="awaiting_confirmation",
        requested_by="operator",
        risk_level="medium",
        impact_summary="single service restart",
        plan_snapshot={
            "machine": {"name": "web-01", "secret": "must-not-appear"},
            "service": {"name": "nginx", "command": "must-not-appear"},
        },
        precheck_result={},
        verification_policy={},
        idempotency_key="idem-01",
        expires_at=datetime.now(timezone.utc),
    )
    assert operation_target(operation) == "nginx · web-01"


def test_empty_overview_returns_real_empty_sections_without_fabricated_data() -> None:
    empty_rows = MagicMock()
    empty_rows.all.return_value = []
    session = AsyncMock()
    session.scalars.side_effect = [empty_rows, empty_rows, empty_rows, empty_rows, empty_rows]
    session.scalar.side_effect = [0, 0, 0]
    empty_result = MagicMock()
    empty_result.all.return_value = []
    session.execute.side_effect = [empty_result, empty_result]

    result = asyncio.run(
        console_overview(
            Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v1/console-overview",
                    "headers": [],
                }
            ),
            None,
            session,
            Settings(skip_database_init=True),
        )
    )

    assert result.fleet.model_dump() == {
        "total": 0,
        "online": 0,
        "unhealthy_services": 0,
    }
    assert result.events.active == 0
    assert result.agents == []
    assert result.attention == []
    assert result.operations.available is True
    assert result.operations.items == []
    assert result.recent_activity == []
    assert result.trust.schema_current is False
