import re
import secrets
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import structlog
from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings
from .security import hash_token

PRINCIPAL_ID_HEADER = b"x-vps-agent-principal-id"
PRINCIPAL_SOURCE_HEADER = b"x-vps-agent-principal-source"
PRINCIPAL_TOKEN_HEADER = b"x-vps-agent-principal-proxy-token"

SYSTEM_READ = "system:read"
FLEET_READ = "fleet:read"
EVENT_READ = "event:read"
VIEWER_CAPABILITIES = frozenset({SYSTEM_READ, FLEET_READ, EVENT_READ})
_USER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}")
logger = structlog.get_logger()


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str
    auth_source: Literal["caddy_basic"]
    organization_id: Literal["local"]
    roles: tuple[Literal["viewer"], ...]
    capabilities: frozenset[str]
    authorization_mode: Literal["shadow", "read_enforced"]


def valid_admin_token(supplied: str | None, settings: Settings) -> bool:
    return bool(
        supplied
        and secrets.compare_digest(hash_token(supplied), hash_token(settings.admin_api_token))
    )


def _single_header(request: Request, name: bytes) -> str:
    values = [value for key, value in request.scope.get("headers", []) if key.lower() == name]
    if len(values) != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_context",
        )
    try:
        value = values[0].decode("ascii")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_context",
        ) from error
    if not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_context",
        )
    return value


def resolve_principal(request: Request, settings: Settings) -> Principal:
    if not settings.principal_context_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_context_disabled",
        )
    user_id = _single_header(request, PRINCIPAL_ID_HEADER)
    source = _single_header(request, PRINCIPAL_SOURCE_HEADER)
    supplied_token = _single_header(request, PRINCIPAL_TOKEN_HEADER)
    configured_token = (
        settings.principal_proxy_token.get_secret_value()
        if settings.principal_proxy_token is not None
        else ""
    )
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_context",
        )
    if source != "caddy_basic" or not _USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_context",
        )
    if user_id not in settings.principal_viewers:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_not_bound",
        )
    return Principal(
        id=f"caddy-basic:{user_id}",
        display_name=user_id,
        auth_source="caddy_basic",
        organization_id="local",
        roles=("viewer",),
        capabilities=VIEWER_CAPABILITIES,
        authorization_mode=(
            "read_enforced" if settings.principal_read_authorization_enabled else "shadow"
        ),
    )


async def current_principal(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Principal:
    principal = resolve_principal(request, settings)
    await logger.ainfo(
        "principal.context_resolved",
        principal_id=principal.id,
        auth_source=principal.auth_source,
        authorization_mode=principal.authorization_mode,
        request_id=str(uuid4()),
    )
    return principal


def require_read_capability(
    capability: str, *, require_legacy_admin_when_disabled: bool = False
):
    async def dependency(
        request: Request,
        x_admin_token: str | None = Header(default=None),
        settings: Settings = Depends(get_settings),
    ) -> None:
        if not settings.principal_read_authorization_enabled:
            if require_legacy_admin_when_disabled and not valid_admin_token(
                x_admin_token, settings
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid admin token",
                )
            return
        if valid_admin_token(x_admin_token, settings):
            return
        principal = resolve_principal(request, settings)
        if capability not in principal.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="principal_capability_denied",
            )

    return dependency


require_system_read = require_read_capability(
    SYSTEM_READ, require_legacy_admin_when_disabled=True
)
require_fleet_read = require_read_capability(FLEET_READ)
require_event_read = require_read_capability(EVENT_READ)
