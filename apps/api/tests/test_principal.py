import asyncio
import json

import pytest
from fastapi import HTTPException, Request

from app.api import router as api_router
from app.config import Settings
from app.conversation_operations import router as conversation_operations_router
from app.m3 import router as m3_router
from app.operations import router as operations_router
from app.principal import (
    EVENT_READ,
    FLEET_READ,
    OPERATION_APPROVE,
    OPERATION_PLAN,
    OPERATION_READ,
    SYSTEM_READ,
    observe_operation_approve,
    observe_operation_plan,
    require_event_read,
    require_fleet_read,
    require_system_read,
    resolve_principal,
    resolve_write_principal,
)

TOKEN = "test-only-" + ("x" * 32)
WRITE_TOKEN = "test-write-only-" + ("y" * 32)
OPERATOR_ID = "local:4bf4ab08-4da6-44bb-8607-3c87f1946012"
APPROVER_ID = "local:7c09f56b-f777-4277-99d8-8ac55b69b0ff"


def role_bindings() -> str:
    return json.dumps(
        [
            {
                "auth_source": "caddy_basic",
                "auth_subject": "ops-alice",
                "principal_id": OPERATOR_ID,
                "display_name": "Alice",
                "roles": ["operator"],
            },
            {
                "auth_source": "caddy_basic",
                "auth_subject": "ops-bob",
                "principal_id": APPROVER_ID,
                "display_name": "Bob",
                "roles": ["approver"],
            },
        ]
    )


def request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def trusted_headers(user_id: str = "admin") -> list[tuple[bytes, bytes]]:
    return [
        (b"x-vps-agent-principal-id", user_id.encode("ascii")),
        (b"x-vps-agent-principal-source", b"caddy_basic"),
        (b"x-vps-agent-principal-proxy-token", TOKEN.encode("ascii")),
    ]


def trusted_write_headers(user_id: str = "ops-alice") -> list[tuple[bytes, bytes]]:
    return [
        (b"x-vps-agent-principal-id", user_id.encode("ascii")),
        (b"x-vps-agent-principal-source", b"caddy_basic"),
        (b"x-vps-agent-principal-write-token", WRITE_TOKEN.encode("ascii")),
    ]


def enabled_settings(*, read: bool = False) -> Settings:
    return Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_read_authorization_enabled=read,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="admin,readonly.user",
    )


def write_shadow_settings() -> Settings:
    return Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="admin",
        principal_write_context_enabled=True,
        principal_write_proxy_token=WRITE_TOKEN,
        principal_role_bindings_json=role_bindings(),
    )


def test_principal_configuration_is_default_off_and_fail_closed() -> None:
    settings = Settings(skip_database_init=True)
    assert settings.principal_context_enabled is False
    assert settings.principal_read_authorization_enabled is False
    assert settings.principal_write_context_enabled is False
    assert settings.principal_write_authorization_enabled is False

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
    with pytest.raises(ValueError, match="write authorization requires"):
        Settings(principal_write_authorization_enabled=True)
    with pytest.raises(ValueError, match="write context requires principal context"):
        Settings(principal_write_context_enabled=True)


def test_resolve_principal_returns_finite_shadow_view() -> None:
    settings = enabled_settings()
    principal = resolve_principal(request_with_headers(trusted_headers()), settings)

    assert TOKEN not in repr(settings)
    assert principal.id == "caddy-basic:admin"
    assert principal.display_name == "admin"
    assert principal.roles == ("viewer",)
    assert principal.capabilities == {SYSTEM_READ, FLEET_READ, EVENT_READ}
    assert principal.authorization_mode == "shadow"
    assert principal.write_authorization_mode == "disabled"


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        ("not-json", "valid JSON"),
        ("{}", "JSON array"),
        (json.dumps([{"unexpected": True}]), "validation error"),
        (
            json.dumps(
                [
                    {
                        "auth_source": "caddy_basic",
                        "auth_subject": 7,
                        "principal_id": OPERATOR_ID,
                        "display_name": "Alice",
                        "roles": ["operator"],
                    }
                ]
            ),
            "validation error",
        ),
    ],
)
def test_role_binding_json_is_strict(bindings: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(principal_role_bindings_json=bindings, skip_database_init=True)


def test_role_binding_json_rejects_extra_fields() -> None:
    bindings = json.loads(role_bindings())
    bindings[0]["unexpected"] = "rejected"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        Settings(
            principal_role_bindings_json=json.dumps(bindings),
            skip_database_init=True,
        )


def test_role_binding_json_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRINCIPAL_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("PRINCIPAL_PROXY_TOKEN", TOKEN)
    monkeypatch.setenv("PRINCIPAL_VIEWER_IDS", "admin")
    monkeypatch.setenv("PRINCIPAL_WRITE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("PRINCIPAL_WRITE_PROXY_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("PRINCIPAL_ROLE_BINDINGS_JSON", role_bindings())

    settings = Settings(_env_file=None, skip_database_init=True)

    assert [binding.auth_subject for binding in settings.principal_role_bindings] == [
        "ops-alice",
        "ops-bob",
    ]
    assert WRITE_TOKEN not in repr(settings)


def test_write_context_configuration_is_fail_closed() -> None:
    base = {
        "skip_database_init": True,
        "principal_context_enabled": True,
        "principal_proxy_token": TOKEN,
        "principal_viewer_ids": "admin",
        "principal_write_context_enabled": True,
        "principal_role_bindings_json": role_bindings(),
    }
    with pytest.raises(ValueError, match="non-placeholder"):
        Settings(**base)
    with pytest.raises(ValueError, match="differ from read token"):
        Settings(**base, principal_write_proxy_token=TOKEN)
    with pytest.raises(ValueError, match="not available in M6.4c1"):
        Settings(
            **base,
            principal_write_proxy_token=WRITE_TOKEN,
            principal_write_authorization_enabled=True,
        )
    one_role = json.dumps(json.loads(role_bindings())[:1])
    with pytest.raises(ValueError, match="distinct operator and approver"):
        Settings(
            **{**base, "principal_role_bindings_json": one_role},
            principal_write_proxy_token=WRITE_TOKEN,
        )
    duplicate = json.loads(role_bindings())
    duplicate[1]["auth_subject"] = duplicate[0]["auth_subject"]
    with pytest.raises(ValueError, match="subjects must be unique"):
        Settings(
            **{**base, "principal_role_bindings_json": json.dumps(duplicate)},
            principal_write_proxy_token=WRITE_TOKEN,
        )


def test_preconfigured_write_bindings_do_not_change_identity_while_disabled() -> None:
    settings = Settings(
        skip_database_init=True,
        principal_context_enabled=True,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="admin",
        principal_role_bindings_json=role_bindings(),
    )
    principal = resolve_principal(
        request_with_headers(trusted_headers("admin")), settings
    )

    assert principal.id == "caddy-basic:admin"
    assert principal.roles == ("viewer",)
    assert principal.write_authorization_mode == "disabled"


@pytest.mark.parametrize(
    ("subject", "principal_id", "role", "write_capability"),
    [
        ("ops-alice", OPERATOR_ID, "operator", OPERATION_PLAN),
        ("ops-bob", APPROVER_ID, "approver", OPERATION_APPROVE),
    ],
)
def test_stable_write_principal_shadow_mapping(
    subject: str, principal_id: str, role: str, write_capability: str
) -> None:
    settings = write_shadow_settings()
    write_principal = resolve_write_principal(
        request_with_headers(trusted_write_headers(subject)), settings
    )
    read_principal = resolve_principal(
        request_with_headers(trusted_headers(subject)), settings
    )

    for principal in (write_principal, read_principal):
        assert principal.id == principal_id
        assert principal.auth_subject == subject
        assert principal.roles == (role,)
        assert principal.capabilities.issuperset(
            {SYSTEM_READ, FLEET_READ, EVENT_READ, OPERATION_READ, write_capability}
        )
        assert principal.write_authorization_mode == "shadow"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        trusted_write_headers()[:-1],
        trusted_write_headers()
        + [(b"x-vps-agent-principal-write-token", WRITE_TOKEN.encode("ascii"))],
        [
            (name, b"wrong-token" if name.endswith(b"write-token") else value)
            for name, value in trusted_write_headers()
        ],
    ],
)
def test_write_principal_rejects_untrusted_context_without_echoing_values(
    headers: list[tuple[bytes, bytes]],
) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_write_principal(request_with_headers(headers), write_shadow_settings())
    assert error.value.status_code == 401
    assert WRITE_TOKEN not in str(error.value.detail)


def test_write_principal_rejects_unbound_subject() -> None:
    with pytest.raises(HTTPException) as error:
        resolve_write_principal(
            request_with_headers(trusted_write_headers("other")),
            write_shadow_settings(),
        )
    assert error.value.status_code == 403
    assert error.value.detail == "principal_write_not_bound"


def test_write_shadow_observation_never_changes_legacy_route_result() -> None:
    settings = write_shadow_settings()
    assert asyncio.run(observe_operation_plan(request_with_headers([]), settings)) is None
    assert (
        asyncio.run(
            observe_operation_plan(
                request_with_headers(trusted_write_headers("ops-alice")), settings
            )
        )
        is None
    )
    assert (
        asyncio.run(
            observe_operation_approve(
                request_with_headers(trusted_write_headers("ops-alice")), settings
            )
        )
        is None
    )


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


def test_write_shadow_dependencies_are_attached_only_to_frozen_post_routes() -> None:
    shadow_dependencies = {observe_operation_plan, observe_operation_approve}
    actual: dict[tuple[str, str], set] = {}
    for route in [*operations_router.routes, *conversation_operations_router.routes]:
        dependencies = {
            item.call
            for item in route.dependant.dependencies
            if item.call in shadow_dependencies
        }
        for method in route.methods or set():
            if dependencies:
                actual[(route.path, method)] = dependencies

    assert actual == {
        ("/api/v1/operations", "POST"): {observe_operation_plan},
        ("/api/v1/deployment-plans", "POST"): {observe_operation_plan},
        ("/api/v1/deployment-operations", "POST"): {observe_operation_plan},
        ("/api/v1/deployment-operations/{operation_id}/rollback", "POST"): {
            observe_operation_plan
        },
        (
            "/api/v1/events/{event_id}/conversation/turns/{turn_id}/restart-plan",
            "POST",
        ): {observe_operation_plan},
        (
            "/api/v1/events/{event_id}/conversation/turns/{turn_id}/rollback-plan",
            "POST",
        ): {observe_operation_plan},
        ("/api/v1/operations/{operation_id}/confirm", "POST"): {
            observe_operation_approve
        },
    }
