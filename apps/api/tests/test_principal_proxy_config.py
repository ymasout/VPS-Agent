from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HEADERS = (
    "X-VPS-Agent-Principal-Id",
    "X-VPS-Agent-Principal-Source",
    "X-VPS-Agent-Principal-Proxy-Token",
)


def test_caddy_overwrites_trusted_headers_and_strips_public_route_headers() -> None:
    caddyfile = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text(encoding="utf-8")

    for header in HEADERS:
        assert caddyfile.count(f"header_up {header} ") == 2
        assert caddyfile.count(f"header_up -{header}") == 2
    assert "header_up X-VPS-Agent-Principal-Id {http.auth.user.id}" in caddyfile
    assert "header_up X-VPS-Agent-Principal-Source caddy_basic" in caddyfile
    assert (
        "header_up X-VPS-Agent-Principal-Proxy-Token {$PRINCIPAL_PROXY_TOKEN}"
        in caddyfile
    )


def test_compose_and_examples_keep_principal_features_default_off() -> None:
    compose = (ROOT / "deploy" / "compose.production.yaml").read_text(encoding="utf-8")
    local_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    production_example = (ROOT / "deploy" / ".env.production.example").read_text(
        encoding="utf-8"
    )

    for name in ("PRINCIPAL_CONTEXT_ENABLED", "PRINCIPAL_READ_AUTHORIZATION_ENABLED"):
        assert f"{name}: ${{{name}:-false}}" in compose
        assert f"{name}=false" in local_example
        assert f"{name}=false" in production_example
    for name in ("PRINCIPAL_PROXY_TOKEN", "PRINCIPAL_VIEWER_IDS"):
        assert f"{name}=" in local_example
        assert f"{name}=" in production_example
