"""Bounded, read-only Operation workspace; no task or transition side effects."""

import base64
import hashlib
import json
from binascii import Error as BinasciiError
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import Operation
from .principal import authorize_operation_read
from .redaction import redact_text
from .schemas import OperationListItem, OperationPage

router = APIRouter(prefix="/api/v1")


def utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def display_text(value: object, fallback: str, limit: int = 160) -> str:
    return redact_text(value if isinstance(value, str) else fallback)[0][:limit]


def operation_list_item(operation: Operation) -> OperationListItem:
    plan = operation.plan_snapshot or {}
    machine = plan.get("machine")
    service = plan.get("service")
    machine = machine if isinstance(machine, dict) else {}
    service = service if isinstance(service, dict) else {}
    return OperationListItem(
        id=operation.id,
        agent_id=operation.agent_id,
        action_type=operation.action_type,
        rollback_of=operation.rollback_of,
        status=operation.status,
        risk_level=operation.risk_level,
        machine=display_text(machine.get("name", machine.get("hostname")), operation.agent_id),
        service=display_text(service.get("name"), operation.instance_id),
        environment=display_text(service.get("environment"), "unknown"),
        requested_by=operation.requested_by,
        confirmed_by=operation.confirmed_by,
        requested_at=operation.requested_at,
        expires_at=operation.expires_at,
        completed_at=operation.completed_at,
        impact_summary=display_text(operation.impact_summary, "", 512),
    )


@router.get(
    "/operations",
    response_model=OperationPage,
    dependencies=[Depends(authorize_operation_read)],
)
async def list_operations(
    operation_status: str | None = Query(default=None, alias="status", min_length=1, max_length=32),
    action_type: str | None = Query(default=None, min_length=1, max_length=32),
    agent_id: str | None = Query(default=None, min_length=1, max_length=36),
    requested_by: str | None = Query(default=None, min_length=1, max_length=128),
    confirmed_by: str | None = Query(default=None, min_length=1, max_length=128),
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> OperationPage:
    try:
        since = utc_datetime(since) if since else None
        until = utc_datetime(until) if until else None
    except (OverflowError, ValueError) as error:
        raise HTTPException(status_code=422, detail="invalid operation time range") from error
    if since and until and since > until:
        raise HTTPException(status_code=422, detail="invalid operation time range")
    filters = [operation_status, action_type, agent_id, requested_by, confirmed_by, since, until]
    fingerprint = hashlib.sha256(json.dumps(filters, default=str).encode()).hexdigest()
    query = select(Operation)
    for column, value in zip(
        [
            Operation.status,
            Operation.action_type,
            Operation.agent_id,
            Operation.requested_by,
            Operation.confirmed_by,
        ],
        filters[:5],
        strict=True,
    ):
        if value is not None:
            query = query.where(column == value)
    if since:
        query = query.where(Operation.requested_at >= since)
    if until:
        query = query.where(Operation.requested_at <= until)
    count_query = select(func.count()).select_from(query.subquery())
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (
                not isinstance(decoded, list)
                or len(decoded) != 4
                or decoded[0] != 1
                or decoded[1] != fingerprint
                or not isinstance(decoded[2], str)
                or not isinstance(decoded[3], str)
                or not 1 <= len(decoded[3]) <= 36
            ):
                raise ValueError
            at = utc_datetime(datetime.fromisoformat(decoded[2]))
        except (BinasciiError, UnicodeDecodeError, ValueError, OverflowError) as error:
            raise HTTPException(status_code=422, detail="invalid operation cursor") from error
        query = query.where(
            or_(
                Operation.requested_at < at,
                and_(Operation.requested_at == at, Operation.id < decoded[3]),
            )
        )
    total = int(await session.scalar(count_query) or 0)
    rows = list(
        (
            await session.scalars(
                query.order_by(Operation.requested_at.desc(), Operation.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    page_rows = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page_rows[-1]
        payload = [1, fingerprint, last.requested_at.isoformat(), last.id]
        next_cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return OperationPage(
        items=[operation_list_item(row) for row in page_rows],
        next_cursor=next_cursor,
        total=total,
    )
