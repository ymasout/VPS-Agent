from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HEADERS = (
    "X-VPS-Agent-Principal-Id",
    "X-VPS-Agent-Principal-Source",
    "X-VPS-Agent-Principal-Proxy-Token",
)
WRITE_HEADER = "X-VPS-Agent-Principal-Write-Token"


def test_caddy_overwrites_trusted_headers_and_strips_public_route_headers() -> None:
    caddyfile = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text(encoding="utf-8")

    for header in HEADERS:
        assert caddyfile.count(f"header_up {header} ") == 3
        assert caddyfile.count(f"header_up -{header}") == 2
    assert "header_up X-VPS-Agent-Principal-Id {http.auth.user.id}" in caddyfile
    assert "header_up X-VPS-Agent-Principal-Source caddy_basic" in caddyfile
    assert (
        "header_up X-VPS-Agent-Principal-Proxy-Token {$PRINCIPAL_PROXY_TOKEN}"
        in caddyfile
    )
    assert (
        "header_up X-VPS-Agent-Principal-Write-Token "
        "{$PRINCIPAL_WRITE_PROXY_TOKEN}" in caddyfile
    )
    assert caddyfile.count(f"header_up -{WRITE_HEADER}") == 4
    assert "method POST" in caddyfile
    for path_fragment in (
        "operations|deployment-plans|deployment-operations",
        "deployment-operations/[^/]+/rollback",
        "operations/[^/]+/confirm",
        "conversation/turns/[^/]+/(restart|rollback)-plan",
    ):
        assert path_fragment in caddyfile
    for user in ("CADDY_ADMIN_USER", "CADDY_OPERATOR_USER", "CADDY_APPROVER_USER"):
        assert caddyfile.count("{$" + user + "}") == 3


def test_compose_and_examples_keep_principal_features_default_off() -> None:
    compose = (ROOT / "deploy" / "compose.production.yaml").read_text(encoding="utf-8")
    local_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    production_example = (ROOT / "deploy" / ".env.production.example").read_text(
        encoding="utf-8"
    )

    for name in (
        "PRINCIPAL_CONTEXT_ENABLED",
        "PRINCIPAL_READ_AUTHORIZATION_ENABLED",
        "PRINCIPAL_WRITE_CONTEXT_ENABLED",
        "PRINCIPAL_WRITE_AUTHORIZATION_ENABLED",
    ):
        assert f"{name}: ${{{name}:-false}}" in compose
        assert f"{name}=false" in local_example
        assert f"{name}=false" in production_example
    for name in (
        "PRINCIPAL_PROXY_TOKEN",
        "PRINCIPAL_VIEWER_IDS",
        "PRINCIPAL_WRITE_PROXY_TOKEN",
        "PRINCIPAL_ROLE_BINDINGS_JSON",
    ):
        assert f"{name}=" in local_example
        assert f"{name}=" in production_example
    web_service = compose.split("\n  web:\n", 1)[1].split("\n  api:\n", 1)[0]
    assert "PRINCIPAL_WRITE_PROXY_TOKEN" not in web_service
    for name in (
        "CADDY_OPERATOR_USER",
        "CADDY_OPERATOR_PASSWORD_HASH",
        "CADDY_APPROVER_USER",
        "CADDY_APPROVER_PASSWORD_HASH",
    ):
        assert f"{name}: ${{{name}:?set {name}}}" in compose
        assert f"{name}=" in production_example
