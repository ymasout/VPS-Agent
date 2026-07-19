import asyncio
import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import quote

import httpx
import jwt
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api import require_admin
from .config import Settings, get_settings
from .database import get_session, session_factory
from .models import (
    GitHubRepositoryBinding,
    GitHubRepositoryFile,
    GitHubWebhookDelivery,
    Repository,
)
from .redaction import redact_text, truncate_utf8
from .schemas import (
    GitHubRepositoryView,
    GitHubStatusView,
    GitHubSyncReceipt,
    GitHubWebhookReceipt,
)

router = APIRouter(prefix="/api/v1/github", tags=["github"])
delivery_pattern = re.compile(r"^[A-Za-z0-9-]{1,128}$")
logger = structlog.get_logger()


def github_is_configured(settings: Settings) -> bool:
    return bool(
        settings.github_app_id
        and settings.github_app_private_key_base64
        and settings.github_app_installation_id
        and settings.github_webhook_secret
    )


def github_allowed_paths(settings: Settings) -> list[str]:
    paths: list[str] = []
    for raw in settings.github_allowed_file_paths.split(","):
        path = raw.strip()
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or len(path) > 512
            or any(part in {"", ".", ".."} for part in parts)
        ):
            continue
        if path not in paths:
            paths.append(path)
        if len(paths) >= 16:
            break
    return paths


@lru_cache(maxsize=2)
def load_github_private_key(encoded_private_key: str) -> PrivateKeyTypes:
    """缓存已解析私钥，避免每次同步重复 Base64 解码和 PEM 解析。"""

    try:
        private_key = base64.b64decode(encoded_private_key, validate=True)
        return serialization.load_pem_private_key(private_key, password=None)
    except (TypeError, ValueError) as error:
        raise RuntimeError("GitHub App private key is not valid base64 PEM") from error


def build_app_jwt(settings: Settings, *, current_time: datetime | None = None) -> str:
    if not github_is_configured(settings):
        raise RuntimeError("GitHub App is not configured")
    now = current_time or datetime.now(timezone.utc)
    private_key = load_github_private_key(settings.github_app_private_key_base64 or "")
    return jwt.encode(
        {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": settings.github_app_id,
        },
        private_key,
        algorithm="RS256",
    )


def verify_webhook_signature(body: bytes, secret: str, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@dataclass
class RepositoryFileSnapshot:
    path: str
    content: str
    content_sha256: str
    byte_size: int
    redacted: bool
    truncated: bool


@dataclass
class SyncedRepository:
    github_repository_id: int
    full_name: str
    default_branch: str
    private: bool
    head_sha: str | None
    files: list[RepositoryFileSnapshot]
    error: str | None = None


class GitHubClient:
    """只使用 GitHub App 安装令牌的只读 REST 客户端。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not github_is_configured(settings):
            raise RuntimeError("GitHub App is not configured")
        self.settings = settings
        self.client = client

    async def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        token: str,
        accept: str = "application/vnd.github+json",
        payload: dict | None = None,
        max_bytes: int = 524288,
    ) -> tuple[bytes, httpx.Headers]:
        headers = {
            "accept": accept,
            "authorization": f"Bearer {token}",
            "x-github-api-version": self.settings.github_api_version,
            "user-agent": "vps-agent-control-plane",
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15.0)
        try:
            async with client.stream(
                method,
                f"{self.settings.github_api_url.rstrip('/')}{path}",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise RuntimeError(f"GitHub response exceeds {max_bytes} bytes")
                return bytes(body), response.headers
        finally:
            if owns_client:
                await client.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        token: str,
        payload: dict | None = None,
        max_bytes: int = 524288,
    ) -> object:
        body, _ = await self._request_bytes(
            method, path, token=token, payload=payload, max_bytes=max_bytes
        )
        return json.loads(body)

    async def installation_token(self) -> str:
        payload = await self._request_json(
            "POST",
            f"/app/installations/{self.settings.github_app_installation_id}/access_tokens",
            token=build_app_jwt(self.settings),
            payload={"permissions": {"contents": "read"}},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
            raise RuntimeError("GitHub installation token response is invalid")
        return payload["token"]

    async def list_repositories(self, token: str) -> list[dict]:
        repositories: list[dict] = []
        for page in range(1, 11):
            payload = await self._request_json(
                "GET",
                f"/installation/repositories?per_page=100&page={page}",
                token=token,
                max_bytes=2 * 1024 * 1024,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), list):
                raise RuntimeError("GitHub repository list response is invalid")
            batch = [item for item in payload["repositories"] if isinstance(item, dict)]
            repositories.extend(batch)
            if len(batch) < 100:
                break
        return repositories

    async def snapshot_repository(self, token: str, repository: dict) -> SyncedRepository:
        full_name = str(repository.get("full_name", ""))
        default_branch = str(repository.get("default_branch") or "main")
        result = SyncedRepository(
            github_repository_id=int(repository["id"]),
            full_name=full_name,
            default_branch=default_branch,
            private=bool(repository.get("private", True)),
            head_sha=None,
            files=[],
        )
        try:
            commit = await self._request_json(
                "GET",
                f"/repos/{quote(full_name, safe='/')}/commits/{quote(default_branch, safe='')}",
                token=token,
            )
            if not isinstance(commit, dict) or not isinstance(commit.get("sha"), str):
                raise RuntimeError("GitHub commit response is invalid")
            result.head_sha = commit["sha"]
            for path in github_allowed_paths(self.settings):
                try:
                    raw, _ = await self._request_bytes(
                        "GET",
                        f"/repos/{quote(full_name, safe='/')}/contents/{quote(path, safe='/')}"
                        f"?ref={quote(result.head_sha, safe='')}",
                        token=token,
                        accept="application/vnd.github.raw+json",
                        max_bytes=self.settings.github_max_file_bytes + 1,
                    )
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 404:
                        continue
                    raise
                truncated_content, truncated = truncate_utf8(
                    raw.decode("utf-8", errors="replace"),
                    self.settings.github_max_file_bytes,
                )
                safe_content, changed = redact_text(truncated_content)
                result.files.append(
                    RepositoryFileSnapshot(
                        path=path,
                        content=safe_content,
                        content_sha256=hashlib.sha256(safe_content.encode()).hexdigest(),
                        byte_size=len(safe_content.encode()),
                        redacted=True,
                        truncated=truncated or len(raw) > self.settings.github_max_file_bytes,
                    )
                )
        except Exception as error:
            result.error = str(error)[:512]
        return result


async def snapshot_repositories(
    client: GitHubClient,
    token: str,
    repositories: list[dict],
    concurrency: int,
) -> list[SyncedRepository]:
    """受限并发读取仓库，避免大安装范围完全串行或瞬时打满 GitHub。"""

    semaphore = asyncio.Semaphore(concurrency)

    async def snapshot(repository: dict) -> SyncedRepository:
        async with semaphore:
            return await client.snapshot_repository(token, repository)

    return list(await asyncio.gather(*(snapshot(item) for item in repositories)))


async def _mark_delivery(delivery_id: str, status_value: str, error: str | None = None) -> None:
    async with session_factory() as session:
        delivery = await session.get(GitHubWebhookDelivery, delivery_id)
        if delivery is not None:
            delivery.status = status_value
            delivery.error = error[:512] if error else None
            delivery.processed_at = datetime.now(timezone.utc)
            await session.commit()


async def revoke_github_installation_bindings(
    session: AsyncSession, installation_id: int
) -> int:
    bindings = list(
        (
            await session.scalars(
                select(GitHubRepositoryBinding).where(
                    GitHubRepositoryBinding.installation_id == installation_id
                )
            )
        ).all()
    )
    for binding in bindings:
        binding.enabled = False
    repository_ids = [binding.repository_id for binding in bindings]
    if repository_ids:
        await session.execute(
            delete(GitHubRepositoryFile).where(
                GitHubRepositoryFile.repository_id.in_(repository_ids)
            )
        )
    return len(bindings)


async def disable_github_installation(settings: Settings, delivery_id: str) -> None:
    """安装被删除或暂停时撤销授权，并清理不再可用的仓库文件快照。"""

    async with session_factory() as session:
        await revoke_github_installation_bindings(
            session, settings.github_app_installation_id or 0
        )
        await session.commit()
    await _mark_delivery(delivery_id, "completed")


async def sync_github_installation(
    settings: Settings,
    delivery_id: str | None = None,
    github_client: GitHubClient | None = None,
) -> int:
    owned_http_client: httpx.AsyncClient | None = None
    try:
        if github_client is None:
            owned_http_client = httpx.AsyncClient(timeout=15.0)
            client = GitHubClient(settings, owned_http_client)
        else:
            client = github_client
        token = await client.installation_token()
        repositories = await client.list_repositories(token)
        snapshots = await snapshot_repositories(
            client,
            token,
            repositories,
            settings.github_sync_concurrency,
        )
        synchronized_at = datetime.now(timezone.utc)
        async with session_factory() as session:
            bindings = list(
                (
                    await session.scalars(
                        select(GitHubRepositoryBinding).where(
                            GitHubRepositoryBinding.installation_id
                            == settings.github_app_installation_id
                        )
                    )
                ).all()
            )
            by_github_id = {item.github_repository_id: item for item in bindings}
            previous_repository_ids = {item.repository_id for item in bindings}
            active_repository_ids: set[str] = set()
            for binding in bindings:
                binding.enabled = False
            for item in snapshots:
                repository = await session.scalar(
                    select(Repository).where(Repository.full_name == item.full_name)
                )
                if repository is None:
                    repository = Repository(
                        full_name=item.full_name,
                        default_branch=item.default_branch,
                    )
                    session.add(repository)
                    await session.flush()
                else:
                    repository.default_branch = item.default_branch
                binding = by_github_id.get(item.github_repository_id)
                if binding is None:
                    binding = GitHubRepositoryBinding(
                        repository_id=repository.id,
                        installation_id=settings.github_app_installation_id,
                        github_repository_id=item.github_repository_id,
                    )
                    session.add(binding)
                binding.repository_id = repository.id
                binding.private = item.private
                binding.enabled = True
                binding.head_sha = item.head_sha
                binding.synchronized_at = synchronized_at
                binding.last_error = item.error
                active_repository_ids.add(repository.id)
                await session.execute(
                    delete(GitHubRepositoryFile).where(
                        GitHubRepositoryFile.repository_id == repository.id
                    )
                )
                if item.head_sha:
                    session.add_all(
                        [
                            GitHubRepositoryFile(
                                repository_id=repository.id,
                                commit_sha=item.head_sha,
                                path=file.path,
                                content=file.content,
                                content_sha256=file.content_sha256,
                                byte_size=file.byte_size,
                                redacted=file.redacted,
                                truncated=file.truncated,
                                fetched_at=synchronized_at,
                            )
                            for file in item.files
                        ]
                    )
            revoked_repository_ids = previous_repository_ids - active_repository_ids
            if revoked_repository_ids:
                await session.execute(
                    delete(GitHubRepositoryFile).where(
                        GitHubRepositoryFile.repository_id.in_(revoked_repository_ids)
                    )
                )
            await session.commit()
        if delivery_id:
            await _mark_delivery(delivery_id, "completed")
        return len(snapshots)
    except Exception as error:
        if delivery_id:
            await _mark_delivery(delivery_id, "failed", str(error))
        raise
    finally:
        if owned_http_client is not None:
            await owned_http_client.aclose()


async def enforce_github_webhook_rate_limit(
    settings: Settings,
    *,
    redis_client: Redis | None = None,
    current_time: datetime | None = None,
) -> None:
    """使用 Redis 提供跨 API 实例的固定窗口限流；Redis 故障时保留验签路径。"""

    limit = settings.github_webhook_rate_limit_per_minute
    if limit == 0:
        return
    now = current_time or datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // 60
    key = f"vps-agent:github:webhook-rate:{bucket}"
    owns_client = redis_client is None
    client = redis_client or Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    try:
        pipeline = client.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, 120)
        count = int((await pipeline.execute())[0])
    except RedisError as error:
        await logger.awarning(
            "github.webhook_rate_limit_unavailable",
            error_type=type(error).__name__,
        )
        return
    finally:
        if owns_client:
            await client.aclose()
    if count > limit:
        raise HTTPException(status_code=429, detail="GitHub webhook rate limit exceeded")


async def list_authorized_repositories(session: AsyncSession) -> list[GitHubRepositoryView]:
    rows = (
        await session.execute(
            select(Repository, GitHubRepositoryBinding)
            .join(
                GitHubRepositoryBinding,
                GitHubRepositoryBinding.repository_id == Repository.id,
            )
            .where(GitHubRepositoryBinding.enabled.is_(True))
            .order_by(Repository.full_name)
        )
    ).all()
    return [
        GitHubRepositoryView(
            id=repository.id,
            full_name=repository.full_name,
            default_branch=repository.default_branch,
            private=binding.private,
            head_sha=binding.head_sha,
            synchronized_at=binding.synchronized_at,
            last_error=binding.last_error,
        )
        for repository, binding in rows
    ]


@router.get("/repositories", response_model=list[GitHubRepositoryView])
async def get_github_repositories(
    session: AsyncSession = Depends(get_session),
) -> list[GitHubRepositoryView]:
    return await list_authorized_repositories(session)


@router.get("/status", response_model=GitHubStatusView)
async def get_github_status(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> GitHubStatusView:
    repository_count = await session.scalar(
        select(func.count())
        .select_from(GitHubRepositoryBinding)
        .where(GitHubRepositoryBinding.enabled.is_(True))
    )
    slug = settings.github_app_slug if github_is_configured(settings) else None
    return GitHubStatusView(
        configured=github_is_configured(settings),
        app_slug=slug,
        installation_url=f"https://github.com/apps/{slug}/installations/new" if slug else None,
        allowed_file_paths=github_allowed_paths(settings),
        repository_count=repository_count or 0,
    )


@router.post(
    "/sync",
    response_model=GitHubSyncReceipt,
    dependencies=[Depends(require_admin)],
)
async def sync_github(settings: Settings = Depends(get_settings)) -> GitHubSyncReceipt:
    if not github_is_configured(settings):
        raise HTTPException(status_code=503, detail="GitHub App is not configured")
    try:
        count = await sync_github_installation(settings)
    except Exception as error:
        raise HTTPException(status_code=502, detail="GitHub synchronization failed") from error
    return GitHubSyncReceipt(repository_count=count)


@router.post("/webhooks", response_model=GitHubWebhookReceipt, status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> GitHubWebhookReceipt:
    if not github_is_configured(settings):
        raise HTTPException(status_code=503, detail="GitHub App is not configured")
    await enforce_github_webhook_rate_limit(settings)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.github_webhook_max_bytes:
            raise HTTPException(status_code=413, detail="GitHub webhook body is too large")
    if not verify_webhook_signature(
        bytes(body), settings.github_webhook_secret or "", x_hub_signature_256
    ):
        raise HTTPException(status_code=401, detail="invalid GitHub webhook signature")
    if not x_github_delivery or not delivery_pattern.fullmatch(x_github_delivery):
        raise HTTPException(status_code=400, detail="invalid GitHub delivery id")
    if not x_github_event or len(x_github_event) > 64:
        raise HTTPException(status_code=400, detail="invalid GitHub event")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="invalid GitHub webhook JSON") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid GitHub webhook payload")
    existing = await session.scalar(
        select(GitHubWebhookDelivery).where(
            GitHubWebhookDelivery.delivery_id == x_github_delivery
        )
    )
    if existing is not None:
        return GitHubWebhookReceipt(duplicate=True)
    installation = payload.get("installation")
    installation_id = installation.get("id") if isinstance(installation, dict) else None
    delivery = GitHubWebhookDelivery(
        delivery_id=x_github_delivery,
        event=x_github_event,
        action=str(payload.get("action"))[:64] if payload.get("action") else None,
        installation_id=installation_id if isinstance(installation_id, int) else None,
    )
    try:
        async with session.begin_nested():
            session.add(delivery)
            await session.flush()
    except IntegrityError:
        return GitHubWebhookReceipt(duplicate=True)
    supported = x_github_event in {"push", "installation", "installation_repositories"}
    configured_installation = settings.github_app_installation_id
    if x_github_event == "ping" or not supported or installation_id != configured_installation:
        delivery.status = "ignored" if x_github_event != "ping" else "completed"
        delivery.processed_at = datetime.now(timezone.utc)
        await session.commit()
        return GitHubWebhookReceipt()
    await session.commit()
    if x_github_event == "installation" and delivery.action in {"deleted", "suspend"}:
        background_tasks.add_task(disable_github_installation, settings, delivery.id)
    else:
        background_tasks.add_task(sync_github_installation, settings, delivery.id)
    return GitHubWebhookReceipt()
