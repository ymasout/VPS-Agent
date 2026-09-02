import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.infrastructure import (
    _decode_cursor,
    _encode_cursor,
    _filter_fingerprint,
    list_service_instances,
    service_inventory_query,
)
from app.m3 import create_service_mapping_batch
from app.m3 import router as m3_router
from app.models import Agent, ManagedService, ServiceInstance, ServiceStatus
from app.principal import authorize_operation_plan
from app.schemas import (
    ServiceMappingBatchCreate,
    ServiceMappingCreate,
    ServiceMappingView,
)


def mapping(agent_id: str, service_key: str) -> ServiceMappingCreate:
    return ServiceMappingCreate(
        name=service_key,
        environment="production",
        agent_id=agent_id,
        service_kind="docker",
        service_key=service_key,
        log_source_key=f"logs-{service_key}",
    )


def mapping_view(agent_id: str, service_key: str) -> ServiceMappingView:
    return ServiceMappingView(
        service_id=f"managed-{service_key}",
        instance_id=f"instance-{service_key}",
        name=service_key,
        environment="production",
        agent_id=agent_id,
        service_kind="docker",
        service_key=service_key,
        deployment_directory=None,
        log_source_key=f"logs-{service_key}",
        repository_full_name=None,
        commit_sha=None,
        image_digest=None,
        criticality="critical",
        restart_enabled=False,
    )


def test_service_inventory_cursor_is_opaque_and_rejects_invalid_values() -> None:
    values = ("api", "web-01", "docker", "status-uuid")
    fingerprint = _filter_fingerprint(
        agent_id="agent-1",
        service_kind="docker",
        environment="production",
        health="healthy",
        mapping="mapped",
        query="api",
    )
    cursor = _encode_cursor(values, fingerprint)
    assert _decode_cursor(cursor, fingerprint) == values
    assert "status-uuid" not in cursor
    with pytest.raises(HTTPException) as error:
        _decode_cursor("not-a-cursor", fingerprint)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        _decode_cursor(cursor, "different-filter-set")
    assert error.value.status_code == 422


def test_service_inventory_query_keeps_filters_and_capability_checks_server_side() -> None:
    sql = str(
        service_inventory_query(
            agent_id="agent-1",
            service_kind="docker",
            environment="production",
            health="unhealthy",
            mapping="mapped",
            query="api",
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "service_statuses.agent_id = 'agent-1'" in sql
    assert "service_statuses.kind = 'docker'" in sql
    assert "managed_services.environment = 'production'" in sql
    assert "service_statuses.healthy IS false" in sql
    assert "service_instances.id IS NOT NULL" in sql
    assert "agent_evidence_source_bindings" in sql
    assert "agent_operation_capabilities" in sql


def test_service_inventory_returns_bounded_safe_display_fields() -> None:
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    observed = ServiceStatus(
        id="status-1",
        agent_id="agent-1",
        kind="docker",
        service_key="internal-stable-key",
        name="api",
        state="running",
        healthy=True,
        observed_at=now,
    )
    last_seen = datetime(2020, 1, 1, tzinfo=timezone.utc)
    agent = Agent(id="agent-1", name="web-01", last_seen_at=last_seen)
    instance = ServiceInstance(
        id="instance-1",
        service_id="managed-1",
        agent_id="agent-1",
        service_kind="docker",
        service_key="internal-stable-key",
        restart_enabled=False,
        deploy_enabled=False,
    )
    managed = ManagedService(
        id="managed-1", name="payments-api", environment="production", criticality="critical"
    )
    result_rows = MagicMock()
    result_rows.all.return_value = [(observed, agent, instance, managed, True, False)]
    session = MagicMock()
    session.scalar = AsyncMock(return_value=1)
    session.execute = AsyncMock(return_value=result_rows)

    result = asyncio.run(
        list_service_instances(
            cursor=None,
            limit=50,
            agent_id=None,
            service_kind=None,
            environment=None,
            health=None,
            mapping=None,
            q=None,
            session=session,
            settings=Settings(skip_database_init=True, agent_offline_after_seconds=90),
        )
    )

    assert result.total == 1
    assert result.next_cursor is None
    assert result.items[0].model_dump() == {
        "inventory_id": "status-1",
        "instance_id": "instance-1",
        "service_id": "managed-1",
        "service_name": "payments-api",
        "environment": "production",
        "agent_id": "agent-1",
        "agent_name": "web-01",
        "agent_online": False,
        "agent_last_seen_at": last_seen,
        "service_kind": "docker",
        "state": "running",
        "healthy": True,
        "observed_at": now,
        "mapped": True,
        "evidence_capable": True,
        "operation_capable": False,
        "restart_enabled": False,
        "deploy_enabled": False,
        "criticality": "critical",
    }
    assert "internal-stable-key" not in result.model_dump_json()


def test_batch_mapping_preserves_input_order_and_partial_success(monkeypatch) -> None:
    payload = ServiceMappingBatchCreate(
        items=[
            {"client_item_id": "first", "mapping": mapping("agent-1", "api")},
            {"client_item_id": "second", "mapping": mapping("agent-1", "worker")},
        ]
    )
    create = AsyncMock(
        side_effect=[mapping_view("agent-1", "api"), HTTPException(409, "already mapped")]
    )
    monkeypatch.setattr("app.m3._create_service_mapping", create)
    nested = MagicMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_nested.return_value = nested
    session.commit = AsyncMock()

    result = asyncio.run(
        create_service_mapping_batch(payload, session, Settings(skip_database_init=True))
    )

    assert [item.client_item_id for item in result.results] == ["first", "second"]
    assert [item.status for item in result.results] == ["created", "rejected"]
    assert result.created_count == 1
    assert result.rejected_count == 1
    assert result.results[1].status_code == 409
    session.commit.assert_awaited_once()


def test_batch_mapping_enforces_server_owned_safe_defaults(monkeypatch) -> None:
    unsafe_mapping = mapping("agent-1", "api").model_copy(
        update={
            "environment": "staging",
            "description": "client supplied",
            "deployment_directory": "/srv/api",
            "repository_full_name": "owner/api",
            "default_branch": "release",
            "commit_sha": "abcdef0",
            "image_digest": "owner/api@sha256:client-supplied",
            "criticality": "non_critical",
            "restart_enabled": True,
        }
    )
    payload = ServiceMappingBatchCreate(
        items=[{"client_item_id": "unsafe", "mapping": unsafe_mapping}]
    )
    create = AsyncMock(return_value=mapping_view("agent-1", "api"))
    monkeypatch.setattr("app.m3._create_service_mapping", create)
    nested = MagicMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_nested.return_value = nested
    session.commit = AsyncMock()

    result = asyncio.run(
        create_service_mapping_batch(payload, session, Settings(skip_database_init=True))
    )

    submitted = create.await_args.args[0]
    assert submitted.model_dump() == {
        **mapping("agent-1", "api").model_dump(),
        "description": None,
        "deployment_directory": None,
        "repository_full_name": None,
        "commit_sha": None,
        "image_digest": None,
    }
    assert result.created_count == 1


def test_batch_mapping_rejects_duplicate_correlation_ids_before_writes() -> None:
    with pytest.raises(ValueError, match="client item ids must be unique"):
        ServiceMappingBatchCreate(
            items=[
                {"client_item_id": "same", "mapping": mapping("agent-1", "api")},
                {"client_item_id": "same", "mapping": mapping("agent-1", "worker")},
            ]
        )


def test_single_and_batch_mapping_share_named_operator_authorization() -> None:
    protected = set()
    for route in m3_router.routes:
        dependencies = {item.call for item in route.dependant.dependencies}
        if authorize_operation_plan in dependencies:
            protected.add((route.path, next(iter(route.methods))))
    assert protected == {
        ("/api/v1/service-mappings", "POST"),
        ("/api/v1/service-mappings/batch", "POST"),
        ("/api/v1/service-instances/{instance_id}/restart-policy", "POST"),
    }
