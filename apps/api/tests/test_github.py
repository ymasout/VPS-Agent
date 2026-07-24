import asyncio
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.config import Settings
from app.github import (
    GitHubClient,
    SyncedRepository,
    build_app_jwt,
    enforce_github_webhook_rate_limit,
    github_allowed_paths,
    github_webhook,
    list_authorized_repositories,
    load_github_private_key,
    revoke_github_installation_bindings,
    snapshot_repositories,
    verify_webhook_signature,
)


def github_settings(**overrides: object) -> Settings:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    values = {
        "github_app_id": "12345",
        "github_app_private_key_base64": base64.b64encode(pem).decode(),
        "github_app_installation_id": 42,
        "github_webhook_secret": "webhook-test-secret",
        "github_allowed_file_paths": "README.md,compose.yaml",
        "github_webhook_rate_limit_per_minute": 0,
    }
    values.update(overrides)
    return Settings(**values)


def request_with_body(body: bytes) -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/"}, receive)


def test_webhook_signature_matches_github_documented_vector() -> None:
    secret = "It's a Secret to Everybody"
    body = b"Hello, World!"
    signature = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

    assert verify_webhook_signature(body, secret, signature)
    assert not verify_webhook_signature(body + b"!", secret, signature)
    assert not verify_webhook_signature(body, secret, None)


def test_app_jwt_uses_short_lived_rs256_claims() -> None:
    load_github_private_key.cache_clear()
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    settings = github_settings()
    token = build_app_jwt(settings, current_time=now)
    build_app_jwt(settings, current_time=now)
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})

    assert header["alg"] == "RS256"
    assert claims["iss"] == "12345"
    assert claims["iat"] == int(now.timestamp()) - 60
    assert claims["exp"] == int(now.timestamp()) + 540
    assert load_github_private_key.cache_info().hits == 1


def test_allowed_file_paths_reject_traversal_and_are_bounded() -> None:
    settings = github_settings(
        github_allowed_file_paths="README.md,../secret,/etc/passwd,deploy/compose.yaml,README.md"
    )

    assert github_allowed_paths(settings) == ["README.md", "deploy/compose.yaml"]


def test_github_client_reads_only_installed_repository_and_redacts_files() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/app/installations/42/access_tokens":
            assert request.method == "POST"
            assert request.headers["authorization"].startswith("Bearer ")
            assert json.loads(request.content) == {"permissions": {"contents": "read"}}
            return httpx.Response(201, json={"token": "installation-token"})
        assert request.headers["authorization"] == "Bearer installation-token"
        if request.url.path == "/installation/repositories":
            return httpx.Response(
                200,
                json={
                    "repositories": [
                        {
                            "id": 101,
                            "full_name": "example/private-service",
                            "default_branch": "main",
                            "private": True,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "a" * 40})
        if request.url.path.endswith("/contents/README.md"):
            return httpx.Response(200, content=b"password=fake-secret\nservice docs")
        if request.url.path.endswith("/contents/compose.yaml"):
            return httpx.Response(404, json={"message": "Not Found"})
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    async def run() -> tuple[list[dict], object]:
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            client = GitHubClient(github_settings(), http_client)
            token = await client.installation_token()
            repositories = await client.list_repositories(token)
            snapshot = await client.snapshot_repository(token, repositories[0])
            return repositories, snapshot
        finally:
            await http_client.aclose()

    repositories, snapshot = asyncio.run(run())

    assert len(repositories) == 1
    assert snapshot.full_name == "example/private-service"
    assert snapshot.head_sha == "a" * 40
    assert len(snapshot.files) == 1
    assert "fake-secret" not in snapshot.files[0].content
    assert "[REDACTED]" in snapshot.files[0].content
    assert all("installation-token" not in str(request.url) for request in requests)


def test_repository_snapshots_use_bounded_concurrency() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0

        async def snapshot_repository(self, _: str, repository: dict) -> SyncedRepository:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return SyncedRepository(
                github_repository_id=repository["id"],
                full_name=repository["full_name"],
                default_branch="main",
                private=True,
                head_sha=None,
                files=[],
            )

    client = FakeClient()
    repositories = [
        {"id": index, "full_name": f"example/repository-{index}"}
        for index in range(6)
    ]
    snapshots = asyncio.run(
        snapshot_repositories(client, "token", repositories, 2)  # type: ignore[arg-type]
    )

    assert len(snapshots) == 6
    assert client.maximum_active == 2


def test_revoking_installation_cleans_repository_file_snapshots() -> None:
    binding = MagicMock(repository_id="repository-1", enabled=True)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [binding]
    session = AsyncMock()
    session.scalars.return_value = scalar_result

    count = asyncio.run(revoke_github_installation_bindings(session, 42))

    assert count == 1
    assert binding.enabled is False
    session.execute.assert_awaited_once()
    assert "DELETE FROM github_repository_files" in str(session.execute.await_args.args[0])


def test_authorized_repository_list_filters_organization_and_installation() -> None:
    rows = MagicMock()
    rows.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = rows

    result = asyncio.run(
        list_authorized_repositories(session, github_settings(), "local")
    )

    assert result == []
    query = session.execute.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "repositories.organization_id" in sql
    assert "github_repository_bindings.installation_id" in sql


def test_webhook_rate_limit_is_shared_through_redis_counter() -> None:
    pipeline = MagicMock()
    pipeline.incr.return_value = pipeline
    pipeline.expire.return_value = pipeline
    pipeline.execute = AsyncMock(return_value=[3, True])
    redis_client = MagicMock()
    redis_client.pipeline.return_value = pipeline
    settings = github_settings(github_webhook_rate_limit_per_minute=2)
    current_time = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            enforce_github_webhook_rate_limit(
                settings,
                redis_client=redis_client,
                current_time=current_time,
            )
        )

    assert error.value.status_code == 429
    bucket = int(current_time.timestamp()) // 60
    pipeline.incr.assert_called_once_with(f"vps-agent:github:webhook-rate:{bucket}")


def test_signed_push_webhook_is_audited_and_schedules_sync() -> None:
    settings = github_settings()
    body = json.dumps({"installation": {"id": 42}, "action": "updated"}).encode()
    signature = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    session = AsyncMock()
    session.scalar.return_value = None
    session.add = MagicMock()
    nested = AsyncMock()
    session.begin_nested = MagicMock(return_value=nested)
    background = BackgroundTasks()

    result = asyncio.run(
        github_webhook(
            request_with_body(body),
            background,
            signature,
            "delivery-01",
            "push",
            session,
            settings,
        )
    )

    assert result.status == "accepted"
    delivery = session.add.call_args.args[0]
    assert delivery.event == "push"
    assert delivery.installation_id == 42
    assert len(background.tasks) == 1
    assert background.tasks[0].func.__name__ == "sync_github_installation"
    session.commit.assert_awaited_once()


def test_webhook_rejects_invalid_signature_before_database_write() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            github_webhook(
                request_with_body(b"{}"),
                BackgroundTasks(),
                "sha256=invalid",
                "delivery-01",
                "push",
                session,
                github_settings(),
            )
        )

    assert error.value.status_code == 401
    session.add.assert_not_called()


def test_installation_suspend_webhook_schedules_local_authorization_revocation() -> None:
    settings = github_settings()
    body = json.dumps({"installation": {"id": 42}, "action": "suspend"}).encode()
    signature = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    session = AsyncMock()
    session.scalar.return_value = None
    session.add = MagicMock()
    nested = AsyncMock()
    session.begin_nested = MagicMock(return_value=nested)
    background = BackgroundTasks()

    result = asyncio.run(
        github_webhook(
            request_with_body(body),
            background,
            signature,
            "delivery-suspend-01",
            "installation",
            session,
            settings,
        )
    )

    assert result.status == "accepted"
    assert len(background.tasks) == 1
    assert background.tasks[0].func.__name__ == "disable_github_installation"
    session.commit.assert_awaited_once()


def test_partial_github_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be set together"):
        Settings(github_app_id="12345")
