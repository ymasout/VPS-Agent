import base64
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from .api import agent_is_online, now_utc
from .config import Settings, get_settings
from .database import get_session
from .models import (
    Agent,
    AgentEvidenceSource,
    AgentEvidenceSourceBinding,
    AgentOperationCapability,
    ManagedService,
    ServiceInstance,
    ServiceStatus,
)
from .principal import require_fleet_read
from .schemas import ServiceInventoryItem, ServiceInventoryPage

router = APIRouter(prefix="/api/v1")


def _filter_fingerprint(
    *,
    agent_id: str | None,
    service_kind: str | None,
    environment: str | None,
    health: str | None,
    mapping: str | None,
    query: str | None,
) -> str:
    payload = json.dumps(
        [agent_id, service_kind, environment, health, mapping, query],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _encode_cursor(values: tuple[str, str, str, str], filter_fingerprint: str) -> str:
    payload = json.dumps(
        [1, filter_fingerprint, *values], ensure_ascii=True, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str, filter_fingerprint: str) -> tuple[str, str, str, str]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid service inventory cursor",
        ) from error
    if (
        not isinstance(decoded, list)
        or len(decoded) != 6
        or decoded[0] != 1
        or decoded[1] != filter_fingerprint
        or any(not isinstance(item, str) for item in decoded[2:])
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid service inventory cursor",
        )
    return tuple(decoded[2:])


def service_inventory_query(
    *,
    agent_id: str | None = None,
    service_kind: str | None = None,
    environment: str | None = None,
    health: Literal["healthy", "unhealthy", "unknown"] | None = None,
    mapping: Literal["mapped", "unmapped"] | None = None,
    query: str | None = None,
):
    evidence_capable = (
        select(literal(True))
        .select_from(AgentEvidenceSourceBinding)
        .join(
            AgentEvidenceSource,
            AgentEvidenceSource.id == AgentEvidenceSourceBinding.evidence_source_id,
        )
        .where(
            AgentEvidenceSource.agent_id == ServiceStatus.agent_id,
            AgentEvidenceSourceBinding.service_kind == ServiceStatus.kind,
            AgentEvidenceSourceBinding.service_key == ServiceStatus.service_key,
        )
        .exists()
    )
    operation_capable = (
        select(literal(True))
        .select_from(AgentOperationCapability)
        .where(
            AgentOperationCapability.agent_id == ServiceStatus.agent_id,
            AgentOperationCapability.service_kind == ServiceStatus.kind,
            AgentOperationCapability.service_key == ServiceStatus.service_key,
        )
        .exists()
    )
    statement = (
        select(
            ServiceStatus,
            Agent,
            ServiceInstance,
            ManagedService,
            evidence_capable.label("evidence_capable"),
            operation_capable.label("operation_capable"),
        )
        .join(Agent, Agent.id == ServiceStatus.agent_id)
        .outerjoin(
            ServiceInstance,
            and_(
                ServiceInstance.agent_id == ServiceStatus.agent_id,
                ServiceInstance.service_kind == ServiceStatus.kind,
                ServiceInstance.service_key == ServiceStatus.service_key,
            ),
        )
        .outerjoin(ManagedService, ManagedService.id == ServiceInstance.service_id)
    )
    filters = []
    if agent_id:
        filters.append(ServiceStatus.agent_id == agent_id)
    if service_kind:
        filters.append(ServiceStatus.kind == service_kind)
    if environment:
        filters.append(ManagedService.environment == environment)
    if health == "healthy":
        filters.append(ServiceStatus.healthy.is_(True))
    elif health == "unhealthy":
        filters.append(ServiceStatus.healthy.is_(False))
    elif health == "unknown":
        filters.append(ServiceStatus.healthy.is_(None))
    if mapping == "mapped":
        filters.append(ServiceInstance.id.is_not(None))
    elif mapping == "unmapped":
        filters.append(ServiceInstance.id.is_(None))
    if query:
        pattern = f"%{query}%"
        filters.append(
            or_(
                ServiceStatus.name.ilike(pattern),
                Agent.name.ilike(pattern),
                ManagedService.name.ilike(pattern),
            )
        )
    return statement.where(*filters)


@router.get(
    "/service-instances",
    response_model=ServiceInventoryPage,
    dependencies=[Depends(require_fleet_read)],
)
async def list_service_instances(
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    agent_id: str | None = Query(default=None, max_length=36),
    service_kind: Literal["docker", "systemd", "http"] | None = None,
    environment: str | None = Query(default=None, min_length=1, max_length=64),
    health: Literal["healthy", "unhealthy", "unknown"] | None = None,
    mapping: Literal["mapped", "unmapped"] | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ServiceInventoryPage:
    filter_fingerprint = _filter_fingerprint(
        agent_id=agent_id,
        service_kind=service_kind,
        environment=environment,
        health=health,
        mapping=mapping,
        query=q,
    )
    statement = service_inventory_query(
        agent_id=agent_id,
        service_kind=service_kind,
        environment=environment,
        health=health,
        mapping=mapping,
        query=q,
    )
    total = int(
        await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    sort_name = func.lower(func.coalesce(ManagedService.name, ServiceStatus.name))
    sort_agent = func.lower(Agent.name)
    sort_columns = (sort_name, sort_agent, ServiceStatus.kind, ServiceStatus.id)
    if cursor:
        statement = statement.where(
            tuple_(*sort_columns) > tuple_(*_decode_cursor(cursor, filter_fingerprint))
        )
    rows = (
        await session.execute(statement.order_by(*sort_columns).limit(limit + 1))
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        ServiceInventoryItem(
            inventory_id=observed.id,
            instance_id=instance.id if instance else None,
            service_id=instance.service_id if instance else None,
            service_name=managed.name if managed else observed.name,
            environment=managed.environment if managed else None,
            agent_id=agent.id,
            agent_name=agent.name,
            agent_online=agent_is_online(
                agent.last_seen_at,
                now_utc(),
                settings.agent_offline_after_seconds,
            ),
            agent_last_seen_at=agent.last_seen_at,
            service_kind=observed.kind,
            state=observed.state,
            healthy=observed.healthy,
            observed_at=observed.observed_at,
            mapped=instance is not None,
            evidence_capable=bool(evidence),
            operation_capable=bool(operation),
            restart_enabled=bool(instance and instance.restart_enabled),
            deploy_enabled=bool(instance and instance.deploy_enabled),
            criticality=managed.criticality if managed else None,
        )
        for observed, agent, instance, managed, evidence, operation in rows
    ]
    next_cursor = None
    if has_more and rows:
        observed, agent, _, managed, _, _ = rows[-1]
        next_cursor = _encode_cursor(
            (
                (managed.name if managed else observed.name).lower(),
                agent.name.lower(),
                observed.kind,
                observed.id,
            ),
            filter_fingerprint,
        )
    return ServiceInventoryPage(items=items, next_cursor=next_cursor, total=total)
