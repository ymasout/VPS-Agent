import asyncio
import json

import pytest
from fastapi import HTTPException, Request

from app.api import router as api_router
from app.config import Settings
from app.conversation_operations import router as conversation_operations_router
from app.m3 import router as m3_router
from app.operations import plan_actor
from app.operations import router as operations_router
from app.principal import (
    EVENT_READ,
    FLEET_READ,
    OPERATION_APPROVE,
    OPERATION_PLAN,
    OPERATION_READ,
    SYSTEM_READ,
    BreakGlassAuthorization,
    authorize_operation_confirmation,
    authorize_operation_plan,
    authorize_operation_read,
    observe_operation_approve,
    observe_operation_plan,
    require_event_read,
    require_fleet_read,
    require_system_read,
    resolve_principal,
    resolve_write_principal,
    validate_same_origin_write,
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


def request_with_headers(
    headers: list[tuple[bytes, bytes]], body: bytes = b""
) -> Request:
    delivered = False

    async def receive() -> dict:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": headers},
        receive,
    )


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


def write_enforced_settings(*, break_glass: bool = False) -> Settings:
    return Settings(
        skip_database_init=True,
        console_public_url="https://ops.example.com",
        principal_context_enabled=True,
        principal_read_authorization_enabled=True,
        principal_proxy_token=TOKEN,
        principal_viewer_ids="admin,ops-alice,ops-bob",
        principal_write_context_enabled=True,
        principal_write_authorization_enabled=True,
        principal_break_glass_enabled=break_glass,
        principal_write_proxy_token=WRITE_TOKEN,
        principal_role_bindings_json=role_bindings(),
    )


def named_write_headers(user_id: str = "ops-alice") -> list[tuple[bytes, bytes]]:
    return trusted_write_headers(user_id) + [
        (b"origin", b"https://ops.example.com"),
        (b"sec-fetch-site", b"same-origin"),
        (b"content-type", b"application/json"),
    ]


def test_principal_configuration_is_default_off_and_fail_closed() -> None:
    settings = Settings(skip_database_init=True)
    assert settings.principal_context_enabled is False
    assert settings.principal_read_authorization_enabled is False
    assert settings.principal_write_context_enabled is False
    assert settings.principal_write_authorization_enabled is False
    assert settings.principal_break_glass_enabled is False

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
    with pytest.raises(ValueError, match="break glass requires"):
        Settings(principal_break_glass_enabled=True)


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
    with pytest.raises(ValueError, match="requires principal read authorization"):
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


def test_named_plan_authorization_accepts_only_operator_and_snapshots_identity() -> None:
    settings = write_enforced_settings()
    principal = asyncio.run(
        authorize_operation_plan(
            request_with_headers(named_write_headers()), None, settings
        )
    )
    assert principal is not None
    assert principal.id == OPERATOR_ID
    assert principal.write_authorization_mode == "enforced"
    assert principal.snapshot(OPERATION_PLAN) == {
        "principal_id": OPERATOR_ID,
        "display_name": "Alice",
        "auth_source": "caddy_basic",
        "auth_subject": "ops-alice",
        "organization_id": "local",
        "roles": ["operator"],
        "capability_used": OPERATION_PLAN,
    }

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            authorize_operation_plan(
                request_with_headers(named_write_headers("ops-bob")), None, settings
            )
        )
    assert error.value.status_code == 403
    assert error.value.detail == "principal_capability_denied"


def test_named_plan_actor_uses_the_same_immutable_snapshot_for_operation_and_transition() -> None:
    principal = resolve_write_principal(
        request_with_headers(trusted_write_headers()), write_enforced_settings()
    )
    actor = plan_actor(principal)
    assert actor["authorization_mode"] == "named"
    assert actor["requested_by"] == OPERATOR_ID
    assert actor["actor_type"] == "principal"
    assert actor["actor_id"] == OPERATOR_ID
    assert actor["requested_principal_snapshot"] == actor["actor_principal_snapshot"]
    assert actor["requested_principal_snapshot"] is not actor["actor_principal_snapshot"]


@pytest.mark.parametrize(
    ("headers", "status_code", "detail"),
    [
        (trusted_write_headers(), 401, "invalid_principal_context"),
        (
            named_write_headers() + [(b"origin", b"https://ops.example.com")],
            401,
            "invalid_principal_context",
        ),
        (
            [
                (name, b"https://evil.example" if name == b"origin" else value)
                for name, value in named_write_headers()
            ],
            403,
            "invalid_write_origin",
        ),
        (
            [
                (name, b"cross-site" if name == b"sec-fetch-site" else value)
                for name, value in named_write_headers()
            ],
            403,
            "invalid_write_fetch_metadata",
        ),
        (
            [
                (name, b"text/plain" if name == b"content-type" else value)
                for name, value in named_write_headers()
            ],
            415,
            "invalid_write_content_type",
        ),
    ],
)
def test_named_write_metadata_fails_closed(
    headers: list[tuple[bytes, bytes]], status_code: int, detail: str
) -> None:
    with pytest.raises(HTTPException) as error:
        validate_same_origin_write(
            request_with_headers(headers), write_enforced_settings()
        )
    assert error.value.status_code == status_code
    assert error.value.detail == detail


def test_c3_confirmation_requires_approver_and_empty_body() -> None:
    settings = write_enforced_settings()
    approver = asyncio.run(
        authorize_operation_confirmation(
            request_with_headers(named_write_headers("ops-bob")), None, settings
        )
    )
    assert approver is not None and approver.id == APPROVER_ID

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            authorize_operation_confirmation(
                request_with_headers(named_write_headers("ops-alice")), None, settings
            )
        )
    assert error.value.status_code == 403
    assert error.value.detail == "principal_capability_denied"

    with pytest.raises(HTTPException) as body_error:
        asyncio.run(
            authorize_operation_confirmation(
                request_with_headers(named_write_headers("ops-bob"), b"{}"),
                None,
                settings,
            )
        )
    assert body_error.value.status_code == 422
    assert body_error.value.detail == "confirmation_body_must_be_empty"

    operator = asyncio.run(
        authorize_operation_read(
            request_with_headers(trusted_headers("ops-alice")), settings
        )
    )
    approver = asyncio.run(
        authorize_operation_read(
            request_with_headers(trusted_headers("ops-bob")), settings
        )
    )
    assert operator is not None and operator.id == OPERATOR_ID
    assert approver is not None and approver.id == APPROVER_ID
    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            authorize_operation_read(
                request_with_headers(trusted_headers("admin")), settings
            )
        )
    assert denied.value.status_code == 403
    assert (
        asyncio.run(
            observe_operation_approve(
                request_with_headers(trusted_write_headers("ops-alice")), settings
            )
        )
        is None
    )


def test_break_glass_requires_explicit_flag_admin_uuid_reason_and_empty_body() -> None:
    request_id = "6aa45c54-108a-4c10-a3ac-7b55c40ca4d7"
    with pytest.raises(HTTPException) as disabled:
        asyncio.run(
            authorize_operation_confirmation(
                request_with_headers([]),
                "change-me-in-production",
                write_enforced_settings(),
                request_id,
                "production incident",
            )
        )
    assert disabled.value.status_code == 403
    assert disabled.value.detail == "principal_break_glass_disabled"

    settings = write_enforced_settings(break_glass=True)
    authorization = asyncio.run(
        authorize_operation_confirmation(
            request_with_headers([]),
            "change-me-in-production",
            settings,
            request_id,
            "production incident",
        )
    )
    assert isinstance(authorization, BreakGlassAuthorization)
    assert authorization.request_id == request_id
    assert authorization.reason == "production incident"

    with pytest.raises(HTTPException) as body_error:
        asyncio.run(
            authorize_operation_confirmation(
                request_with_headers([], b"{}"),
                "change-me-in-production",
                settings,
                request_id,
                "production incident",
            )
        )
    assert body_error.value.status_code == 422
    assert body_error.value.detail == "confirmation_body_must_be_empty"


@pytest.mark.parametrize(
    ("request_id", "reason", "detail"),
    [
        (None, "production incident", "invalid_break_glass_request_id"),
        ("not-a-uuid", "production incident", "invalid_break_glass_request_id"),
        (
            "6aa45c54-108a-4c10-a3ac-7b55c40ca4d7",
            "",
            "invalid_break_glass_reason",
        ),
        (
            "6aa45c54-108a-4c10-a3ac-7b55c40ca4d7",
            " production incident",
            "invalid_break_glass_reason",
        ),
    ],
)
def test_break_glass_rejects_partial_or_invalid_audit_context(
    request_id: str | None, reason: str, detail: str
) -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            authorize_operation_confirmation(
                request_with_headers([]),
                "change-me-in-production",
                write_enforced_settings(break_glass=True),
                request_id,
                reason,
            )
        )
    assert error.value.status_code == 422
    assert error.value.detail == detail


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


def test_operation_dependencies_are_attached_only_to_frozen_routes() -> None:
    operation_dependencies = {
        authorize_operation_plan,
        authorize_operation_confirmation,
        authorize_operation_read,
    }
    actual: dict[tuple[str, str], set] = {}
    for route in [*operations_router.routes, *conversation_operations_router.routes]:
        dependencies = {
            item.call
            for item in route.dependant.dependencies
            if item.call in operation_dependencies
        }
        for method in route.methods or set():
            if dependencies:
                actual[(route.path, method)] = dependencies

    assert actual == {
        ("/api/v1/operations", "POST"): {authorize_operation_plan},
        ("/api/v1/deployment-plans", "POST"): {authorize_operation_plan},
        ("/api/v1/deployment-operations", "POST"): {authorize_operation_plan},
        ("/api/v1/deployment-operations/{operation_id}/rollback", "POST"): {
            authorize_operation_plan
        },
        (
            "/api/v1/events/{event_id}/conversation/turns/{turn_id}/restart-plan",
            "POST",
        ): {authorize_operation_plan},
        (
            "/api/v1/events/{event_id}/conversation/turns/{turn_id}/rollback-plan",
            "POST",
        ): {authorize_operation_plan},
        ("/api/v1/operations/{operation_id}/confirm", "POST"): {
            authorize_operation_confirmation
        },
        ("/api/v1/operations/{operation_id}", "GET"): {authorize_operation_read},
    }
