import asyncio

import pytest
from fastapi import HTTPException, Request

from app.api import router as api_router
from app.config import Settings
from app.m3 import router as m3_router
from app.principal import (
    EVENT_READ,
    FLEET_READ,
    SYSTEM_READ,
    require_event_read,
    require_fleet_read,
    require_system_read,
    resolve_principal,
)

TOKEN = "test-only-" + ("x" * 32)


def request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def trusted_headers(user_id: str = "admin") -> list[tuple[bytes, bytes]]:
    return [
        (b"x-vps-agent-principal-id", user_id.encode("ascii")),
        (b"x-vps-agent-principal-source", b"caddy_basic"),
        (b"x-vps-agent-principal-proxy-token", TOKEN.encode("ascii")),
    ]


def enabled_settings(*, read: bool = False) -> Settings:
    return Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_read_authorization_enabled=read,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="admin,readonly.user",
    )


def test_principal_configuration_is_default_off_and_fail_closed() -> None:
    settings = Settings(skip_database_init=True)
    assert settings.principal_context_enabled is False
    assert settings.principal_read_authorization_enabled is False

    with pytest.raises(ValueError, match="requires principal context"):
        Settings(principal_read_authorization_enabled=True)
    with pytest.raises(ValueError, match="non-placeholder"):
        Settings(principal_context_enabled=True, principal_proxy_token="change-me")
    with pytest.raises(ValueError, match="viewer id is required"):
        Settings(principal_context_enabled=True, principal_proxy_token=TOKEN)
    with pytest.raises(ValueError, match="duplicates"):
        Settings(principal_viewer_ids="admin,admin")
    with pytest.raises(ValueError, match="viewer id is invalid"):
        Settings(principal_viewer_ids="admin,not allowed")


def test_resolve_principal_returns_finite_shadow_view() -> None:
    settings = enabled_settings()
    principal = resolve_principal(request_with_headers(trusted_headers()), settings)

    assert TOKEN not in repr(settings)
    assert principal.id == "caddy-basic:admin"
    assert principal.display_name == "admin"
    assert principal.roles == ("viewer",)
    assert principal.capabilities == {SYSTEM_READ, FLEET_READ, EVENT_READ}
    assert principal.authorization_mode == "shadow"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        trusted_headers()[:-1],
        trusted_headers() + [(b"x-vps-agent-principal-id", b"other")],
        [
            (name, b"wrong-token" if name.endswith(b"proxy-token") else value)
            for name, value in trusted_headers()
        ],
        [
            (name, b"unknown" if name.endswith(b"source") else value)
            for name, value in trusted_headers()
        ],
        trusted_headers("invalid user"),
    ],
)
def test_resolve_principal_rejects_untrusted_context_without_echoing_values(
    headers: list[tuple[bytes, bytes]],
) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_principal(request_with_headers(headers), enabled_settings())
    assert error.value.status_code == 401
    assert error.value.detail == "invalid_principal_context"
    assert TOKEN not in str(error.value.detail)


def test_resolve_principal_rejects_valid_but_unbound_identity() -> None:
    with pytest.raises(HTTPException) as error:
        resolve_principal(request_with_headers(trusted_headers("other")), enabled_settings())
    assert error.value.status_code == 403
    assert error.value.detail == "principal_not_bound"


def test_read_dependencies_preserve_legacy_behavior_while_disabled() -> None:
    request = request_with_headers([])
    settings = Settings(admin_api_token="admin-secret", skip_database_init=True)

    assert asyncio.run(require_fleet_read(request, None, settings)) is None
    assert asyncio.run(require_event_read(request, None, settings)) is None
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_system_read(request, None, settings))
    assert error.value.status_code == 401
    assert asyncio.run(require_system_read(request, "admin-secret", settings)) is None


@pytest.mark.parametrize(
    "dependency", [require_system_read, require_fleet_read, require_event_read]
)
def test_read_dependencies_accept_trusted_viewer_or_legacy_admin(dependency) -> None:
    settings = enabled_settings(read=True)
    assert asyncio.run(
        dependency(request_with_headers(trusted_headers()), None, settings)
    ) is None
    assert (
        asyncio.run(
            dependency(request_with_headers([]), "change-me-in-production", settings)
        )
        is None
    )


def test_read_dependencies_fail_closed_without_trusted_context() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_fleet_read(request_with_headers([]), None, enabled_settings(read=True)))
    assert error.value.status_code == 401


def test_capability_dependencies_are_attached_only_to_the_five_frozen_get_routes() -> None:
    capability_dependencies = {
        require_system_read,
        require_fleet_read,
        require_event_read,
    }
    actual: dict[tuple[str, str], set] = {}
    for route in [*api_router.routes, *m3_router.routes]:
        dependencies = {
            item.call
            for item in route.dependant.dependencies
            if item.call in capability_dependencies
        }
        for method in route.methods or set():
            if dependencies:
                actual[(route.path, method)] = dependencies

    assert actual == {
        ("/api/v1/system-info", "GET"): {require_system_read},
        ("/api/v1/agents", "GET"): {require_fleet_read},
        ("/api/v1/agents/{agent_id}", "GET"): {require_fleet_read},
        ("/api/v1/events", "GET"): {require_event_read},
        ("/api/v1/events/{event_id}", "GET"): {require_event_read},
    }
