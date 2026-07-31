import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings
from .security import hash_token

PRINCIPAL_ID_HEADER = b"x-vps-agent-principal-id"
PRINCIPAL_SOURCE_HEADER = b"x-vps-agent-principal-source"
PRINCIPAL_TOKEN_HEADER = b"x-vps-agent-principal-proxy-token"
PRINCIPAL_WRITE_TOKEN_HEADER = b"x-vps-agent-principal-write-token"
ORIGIN_HEADER = b"origin"
FETCH_SITE_HEADER = b"sec-fetch-site"
CONTENT_TYPE_HEADER = b"content-type"

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

    def snapshot(self, capability: str) -> dict:
        return {
            "principal_id": self.id,
            "display_name": self.display_name,
            "auth_source": self.auth_source,
            "auth_subject": self.auth_subject,
            "organization_id": self.organization_id,
            "roles": list(self.roles),
            "capability_used": capability,
        }


@dataclass(frozen=True)
class BreakGlassAuthorization:
    request_id: str
    reason: str

    def snapshot(self) -> dict:
        return {
            "principal_id": "break-glass:local-admin",
            "display_name": "Emergency local administrator",
            "auth_source": "admin_token",
            "auth_subject": "local-admin",
            "organization_id": "local",
            "roles": ["break_glass"],
            "capability_used": OPERATION_APPROVE,
        }


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
        write_authorization_mode=(
            "enforced" if settings.principal_write_authorization_enabled else "shadow"
        ),
    )


def _expected_origin(settings: Settings) -> str:
    parsed = urlsplit(settings.console_public_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="principal_write_origin_not_configured",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_same_origin_write(request: Request, settings: Settings) -> None:
    origin = _single_header(request, ORIGIN_HEADER)
    fetch_site = _single_header(request, FETCH_SITE_HEADER)
    content_type = _single_header(request, CONTENT_TYPE_HEADER)
    if not secrets.compare_digest(origin, _expected_origin(settings)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid_write_origin",
        )
    if fetch_site != "same-origin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid_write_fetch_metadata",
        )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="invalid_write_content_type",
        )


async def authorize_operation_plan(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal | None:
    if not settings.principal_write_authorization_enabled:
        await observe_operation_plan(request, settings)
        if not valid_admin_token(x_admin_token, settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin token",
            )
        return None
    validate_same_origin_write(request, settings)
    principal = resolve_write_principal(request, settings)
    if OPERATION_PLAN not in principal.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_capability_denied",
        )
    return principal


async def authorize_operation_confirmation(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
    x_vps_agent_break_glass_reason: Annotated[
        str | None, Header(alias="X-VPS-Agent-Break-Glass-Reason")
    ] = None,
) -> Principal | BreakGlassAuthorization | None:
    if not settings.principal_write_authorization_enabled:
        await observe_operation_approve(request, settings)
        if not valid_admin_token(x_admin_token, settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin token",
            )
        return None

    break_glass_requested = bool(
        idempotency_key is not None or x_vps_agent_break_glass_reason is not None
    )
    if break_glass_requested:
        if not settings.principal_break_glass_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="principal_break_glass_disabled",
            )
        if not valid_admin_token(x_admin_token, settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin token",
            )
        try:
            parsed_request_id = UUID(idempotency_key or "")
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid_break_glass_request_id",
            ) from error
        if (
            parsed_request_id.version != 4
            or str(parsed_request_id) != idempotency_key
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid_break_glass_request_id",
            )
        reason = x_vps_agent_break_glass_reason or ""
        if (
            reason != reason.strip()
            or not 1 <= len(reason) <= 256
            or any(ord(character) < 32 or ord(character) == 127 for character in reason)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid_break_glass_reason",
            )
        if await request.body():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="confirmation_body_must_be_empty",
            )
        return BreakGlassAuthorization(request_id=idempotency_key, reason=reason)

    validate_same_origin_write(request, settings)
    if await request.body():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirmation_body_must_be_empty",
        )
    principal = resolve_write_principal(request, settings)
    if OPERATION_APPROVE not in principal.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_capability_denied",
        )
    return principal


async def authorize_operation_read(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Principal | None:
    if not settings.principal_write_authorization_enabled:
        return None
    principal = resolve_principal(request, settings)
    if OPERATION_READ not in principal.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="principal_capability_denied",
        )
    return principal


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
