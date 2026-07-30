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
PRINCIPAL_WRITE_TOKEN_HEADER = b"x-vps-agent-principal-write-token"

SYSTEM_READ = "system:read"
FLEET_READ = "fleet:read"
EVENT_READ = "event:read"
OPERATION_READ = "operation:read"
OPERATION_PLAN = "operation:plan"
OPERATION_APPROVE = "operation:approve"
VIEWER_CAPABILITIES = frozenset({SYSTEM_READ, FLEET_READ, EVENT_READ})
ROLE_CAPABILITIES = {
    "operator": VIEWER_CAPABILITIES | {OPERATION_READ, OPERATION_PLAN},
    "approver": VIEWER_CAPABILITIES | {OPERATION_READ, OPERATION_APPROVE},
}
_USER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}")
logger = structlog.get_logger()


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str
    auth_source: Literal["caddy_basic"]
    auth_subject: str
    organization_id: Literal["local"]
    roles: tuple[Literal["viewer", "operator", "approver"], ...]
    capabilities: frozenset[str]
    authorization_mode: Literal["shadow", "read_enforced"]
    write_authorization_mode: Literal["disabled", "shadow", "enforced"]


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
    binding = (
        settings.principal_role_binding(user_id)
        if settings.principal_write_context_enabled
        else None
    )
    if user_id not in settings.principal_viewers and binding is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_not_bound",
        )
    role = binding.roles[0] if binding is not None else "viewer"
    return Principal(
        id=binding.principal_id if binding is not None else f"caddy-basic:{user_id}",
        display_name=binding.display_name if binding is not None else user_id,
        auth_source="caddy_basic",
        auth_subject=user_id,
        organization_id="local",
        roles=(role,),
        capabilities=ROLE_CAPABILITIES.get(role, VIEWER_CAPABILITIES),
        authorization_mode=(
            "read_enforced" if settings.principal_read_authorization_enabled else "shadow"
        ),
        write_authorization_mode=(
            "shadow"
            if settings.principal_write_context_enabled
            else "disabled"
        ),
    )


def resolve_write_principal(request: Request, settings: Settings) -> Principal:
    if not settings.principal_write_context_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_write_context_disabled",
        )
    auth_subject = _single_header(request, PRINCIPAL_ID_HEADER)
    source = _single_header(request, PRINCIPAL_SOURCE_HEADER)
    supplied_token = _single_header(request, PRINCIPAL_WRITE_TOKEN_HEADER)
    configured_token = (
        settings.principal_write_proxy_token.get_secret_value()
        if settings.principal_write_proxy_token is not None
        else ""
    )
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_write_context",
        )
    if source != "caddy_basic" or not _USER_ID_PATTERN.fullmatch(auth_subject):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_principal_write_context",
        )
    binding = settings.principal_role_binding(auth_subject)
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_write_not_bound",
        )
    role = binding.roles[0]
    return Principal(
        id=binding.principal_id,
        display_name=binding.display_name,
        auth_source="caddy_basic",
        auth_subject=auth_subject,
        organization_id="local",
        roles=(role,),
        capabilities=ROLE_CAPABILITIES[role],
        authorization_mode=(
            "read_enforced" if settings.principal_read_authorization_enabled else "shadow"
        ),
        write_authorization_mode="shadow",
    )


def observe_write_capability(capability: str):
    async def dependency(
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> None:
        if not settings.principal_write_context_enabled:
            return
        try:
            principal = resolve_write_principal(request, settings)
        except HTTPException as error:
            await logger.awarning(
                "principal.write_shadow",
                decision="untrusted",
                capability=capability,
                reason=error.detail,
                request_id=str(uuid4()),
            )
            return
        await logger.ainfo(
            "principal.write_shadow",
            decision="would_allow" if capability in principal.capabilities else "would_deny",
            capability=capability,
            principal_id=principal.id,
            roles=list(principal.roles),
            request_id=str(uuid4()),
        )

    return dependency


observe_operation_plan = observe_write_capability(OPERATION_PLAN)
observe_operation_approve = observe_write_capability(OPERATION_APPROVE)


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
