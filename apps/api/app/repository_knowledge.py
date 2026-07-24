import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import (
    Agent,
    AlertEvent,
    DeploymentVersion,
    GitHubRepositoryBinding,
    GitHubRepositoryFile,
    ManagedService,
    Repository,
    ServiceInstance,
)
from .redaction import redact_text, truncate_utf8

MAX_REPOSITORY_FILES = 16
MAX_EXCERPTS_PER_FILE = 2
ASCII_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{1,63}")
CJK_TERM = re.compile(r"[\u3400-\u9fff]{2,16}")
QUOTED_TERM = re.compile(r"[\"'“”‘’`]([^\"'“”‘’`]{2,64})[\"'“”‘’`]")
STOP_TERMS = {
    "什么",
    "哪些",
    "这个",
    "当前",
    "事件",
    "问题",
    "是否",
    "怎么",
    "如何",
    "please",
    "what",
    "which",
    "this",
    "that",
    "the",
}


@dataclass(frozen=True)
class RepositoryKnowledgeItem:
    repository_file_id: str
    repository_id: str
    full_name: str
    path: str
    repository_commit_sha: str
    deployment_commit_sha: str | None
    deployment_relation: str
    content_sha256: str
    excerpt: str
    fetched_at: datetime
    synchronized_at: datetime | None
    truncated: bool
    stale: bool
    basis: str = "deployment"


@dataclass(frozen=True)
class RepositorySnapshotState:
    repository: Repository
    binding: GitHubRepositoryBinding | None
    files: list[GitHubRepositoryFile]
    available: bool
    unavailable_reason: str | None


async def repository_snapshot_state(
    session: AsyncSession,
    repository_id: str,
    organization_id: str,
    settings: Settings,
) -> RepositorySnapshotState | None:
    repository = await session.scalar(
        select(Repository).where(
            Repository.id == repository_id,
            Repository.organization_id == organization_id,
        )
    )
    if repository is None:
        return None
    binding = await session.scalar(
        select(GitHubRepositoryBinding).where(
            GitHubRepositoryBinding.repository_id == repository.id
        )
    )
    reason: str | None = None
    if settings.github_app_installation_id is None:
        reason = "repository_unavailable"
    elif (
        binding is None
        or binding.installation_id != settings.github_app_installation_id
        or not binding.enabled
    ):
        reason = "repository_unavailable"
    elif binding.last_error is not None:
        reason = "repository_sync_failed"
    elif binding.head_sha is None:
        reason = "repository_snapshot_missing"
    files: list[GitHubRepositoryFile] = []
    if reason is None and binding is not None and binding.head_sha is not None:
        files = list(
            (
                await session.scalars(
                    select(GitHubRepositoryFile)
                    .where(
                        GitHubRepositoryFile.repository_id == repository.id,
                        GitHubRepositoryFile.commit_sha == binding.head_sha,
                    )
                    .order_by(GitHubRepositoryFile.path, GitHubRepositoryFile.id)
                    .limit(MAX_REPOSITORY_FILES)
                )
            ).all()
        )
        if not files:
            reason = "repository_snapshot_missing"
    return RepositorySnapshotState(
        repository=repository,
        binding=binding,
        files=files,
        available=reason is None,
        unavailable_reason=reason,
    )


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def extract_query_terms(question: str, max_terms: int) -> list[str]:
    normalized = normalize_text(question)
    candidates: list[str] = []
    candidates.extend(match.group(1) for match in QUOTED_TERM.finditer(normalized))
    candidates.extend(match.group(0) for match in ASCII_TERM.finditer(normalized))
    candidates.extend(match.group(0) for match in CJK_TERM.finditer(normalized))
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = normalize_text(candidate).strip("\"'`“”‘’")
        if not term or term in STOP_TERMS or term in seen or len(term.encode("utf-8")) > 192:
            continue
        seen.add(term)
        result.append(term)
        if len(result) >= max_terms:
            break
    return result


def deployment_relation(
    deployment_commit_sha: str | None,
    repository_commit_sha: str,
) -> str:
    if not deployment_commit_sha:
        return "unknown"
    if deployment_commit_sha.lower() == repository_commit_sha.lower():
        return "aligned"
    return "mismatch"


def excerpt_for_terms(
    content: str,
    terms: list[str],
    max_excerpt_bytes: int,
) -> tuple[str, int]:
    lines = content.splitlines() or [content]
    hits: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        hit_count = sum(normalized.count(term) for term in terms)
        if hit_count:
            hits.append((index, hit_count))
    hits.sort(key=lambda item: (-item[1], item[0]))
    excerpts: list[str] = []
    used_lines: set[int] = set()
    total_hits = 0
    for index, hit_count in hits:
        if len(excerpts) >= MAX_EXCERPTS_PER_FILE or index in used_lines:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        used_lines.update(range(start, end))
        excerpt, _ = truncate_utf8("\n".join(lines[start:end]), max_excerpt_bytes)
        if excerpt:
            excerpts.append(excerpt)
            total_hits += hit_count
    safe_excerpt, _ = redact_text("\n…\n".join(excerpts))
    return safe_excerpt, total_hits


async def repository_knowledge_for_event(
    session: AsyncSession,
    event: AlertEvent,
    organization_id: str,
    question: str,
    settings: Settings,
) -> list[RepositoryKnowledgeItem]:
    if (
        not settings.conversation_repository_knowledge_enabled
        or settings.github_app_installation_id is None
        or event.source != "service"
        or not event.service_kind
        or not event.service_key
    ):
        return []
    terms = extract_query_terms(question, settings.conversation_repository_max_terms)
    if not terms:
        return []

    instances = list(
        (
            await session.scalars(
                select(ServiceInstance)
                .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
                .join(Agent, Agent.id == ServiceInstance.agent_id)
                .where(
                    ServiceInstance.agent_id == event.agent_id,
                    ServiceInstance.service_kind == event.service_kind,
                    ServiceInstance.service_key == event.service_key,
                    ManagedService.organization_id == organization_id,
                    Agent.organization_id == organization_id,
                )
                .order_by(ServiceInstance.id)
                .limit(2)
            )
        ).all()
    )
    if len(instances) != 1:
        return []
    instance = instances[0]
    deployment = await session.scalar(
        select(DeploymentVersion)
        .where(DeploymentVersion.instance_id == instance.id)
        .order_by(DeploymentVersion.recorded_at.desc(), DeploymentVersion.id.desc())
        .limit(1)
    )
    if deployment is None or deployment.repository_id is None:
        return []
    repository = await session.scalar(
        select(Repository).where(
            Repository.id == deployment.repository_id,
            Repository.organization_id == organization_id,
        )
    )
    if repository is None:
        return []
    binding = await session.scalar(
        select(GitHubRepositoryBinding).where(
            GitHubRepositoryBinding.repository_id == repository.id,
            GitHubRepositoryBinding.installation_id == settings.github_app_installation_id,
            GitHubRepositoryBinding.enabled.is_(True),
            GitHubRepositoryBinding.last_error.is_(None),
            GitHubRepositoryBinding.head_sha.is_not(None),
        )
    )
    if binding is None or binding.head_sha is None:
        return []
    files = list(
        (
            await session.scalars(
                select(GitHubRepositoryFile)
                .where(
                    GitHubRepositoryFile.repository_id == repository.id,
                    GitHubRepositoryFile.commit_sha == binding.head_sha,
                )
                .order_by(GitHubRepositoryFile.path, GitHubRepositoryFile.id)
                .limit(MAX_REPOSITORY_FILES)
            )
        ).all()
    )
    relation = deployment_relation(deployment.commit_sha, binding.head_sha)
    now = datetime.now(timezone.utc)
    stale = (
        binding.synchronized_at is None
        or (now - binding.synchronized_at).total_seconds()
        > settings.conversation_repository_stale_seconds
    )
    ranked: list[tuple[tuple[int, int, int, str, str], RepositoryKnowledgeItem]] = []
    for file in files:
        normalized_path = normalize_text(file.path)
        normalized_content = normalize_text(file.content)
        distinct_hits = sum(
            1 for term in terms if term in normalized_path or term in normalized_content
        )
        if not distinct_hits:
            continue
        excerpt, content_hits = excerpt_for_terms(
            file.content,
            terms,
            settings.conversation_repository_max_excerpt_bytes,
        )
        path_hits = sum(normalized_path.count(term) for term in terms)
        if not excerpt and path_hits:
            excerpt = f"匹配白名单路径：{file.path}"
        if not excerpt:
            continue
        item = RepositoryKnowledgeItem(
            repository_file_id=file.id,
            repository_id=repository.id,
            full_name=repository.full_name,
            path=file.path,
            repository_commit_sha=file.commit_sha,
            deployment_commit_sha=deployment.commit_sha,
            deployment_relation=relation,
            content_sha256=file.content_sha256,
            excerpt=excerpt,
            fetched_at=file.fetched_at,
            synchronized_at=binding.synchronized_at,
            truncated=file.truncated,
            stale=stale,
        )
        rank = (
            0 if relation == "aligned" else 1,
            -path_hits,
            -(distinct_hits * 1000 + content_hits),
            file.path,
            file.id,
        )
        ranked.append((rank, item))
    ranked.sort(key=lambda item: item[0])
    return [item for _, item in ranked[: settings.conversation_repository_max_results]]


async def repository_knowledge_for_repository(
    session: AsyncSession,
    repository_id: str,
    organization_id: str,
    question: str,
    settings: Settings,
) -> tuple[RepositorySnapshotState | None, list[RepositoryKnowledgeItem]]:
    state = await repository_snapshot_state(
        session,
        repository_id,
        organization_id,
        settings,
    )
    if (
        state is None
        or not state.available
        or not settings.conversation_repository_chat_enabled
        or state.binding is None
        or state.binding.head_sha is None
    ):
        return state, []
    terms = extract_query_terms(question, settings.conversation_repository_max_terms)
    if not terms:
        return state, []
    now = datetime.now(timezone.utc)
    stale = (
        state.binding.synchronized_at is None
        or (now - state.binding.synchronized_at).total_seconds()
        > settings.conversation_repository_stale_seconds
    )
    ranked: list[tuple[tuple[int, int, str, str], RepositoryKnowledgeItem]] = []
    for file in state.files:
        normalized_path = normalize_text(file.path)
        normalized_content = normalize_text(file.content)
        distinct_hits = sum(
            1 for term in terms if term in normalized_path or term in normalized_content
        )
        if not distinct_hits:
            continue
        excerpt, content_hits = excerpt_for_terms(
            file.content,
            terms,
            settings.conversation_repository_max_excerpt_bytes,
        )
        path_hits = sum(normalized_path.count(term) for term in terms)
        if not excerpt and path_hits:
            excerpt = f"匹配白名单路径：{file.path}"
        if not excerpt:
            continue
        item = RepositoryKnowledgeItem(
            repository_file_id=file.id,
            repository_id=state.repository.id,
            full_name=state.repository.full_name,
            path=file.path,
            repository_commit_sha=file.commit_sha,
            deployment_commit_sha=None,
            deployment_relation="unknown",
            content_sha256=file.content_sha256,
            excerpt=excerpt,
            fetched_at=file.fetched_at,
            synchronized_at=state.binding.synchronized_at,
            truncated=file.truncated,
            stale=stale,
            basis="snapshot",
        )
        rank = (
            -path_hits,
            -(distinct_hits * 1000 + content_hits),
            file.path,
            file.id,
        )
        ranked.append((rank, item))
    ranked.sort(key=lambda item: item[0])
    return (
        state,
        [item for _, item in ranked[: settings.conversation_repository_max_results]],
    )


async def repository_knowledge_item_is_current(
    session: AsyncSession,
    event: AlertEvent,
    organization_id: str,
    item: RepositoryKnowledgeItem,
    settings: Settings,
) -> bool:
    if (
        not settings.conversation_repository_knowledge_enabled
        or settings.github_app_installation_id is None
        or item.basis != "deployment"
        or event.source != "service"
        or not event.service_kind
        or not event.service_key
    ):
        return False
    instances = list(
        (
            await session.scalars(
                select(ServiceInstance)
                .join(ManagedService, ManagedService.id == ServiceInstance.service_id)
                .join(Agent, Agent.id == ServiceInstance.agent_id)
                .where(
                    ServiceInstance.agent_id == event.agent_id,
                    ServiceInstance.service_kind == event.service_kind,
                    ServiceInstance.service_key == event.service_key,
                    ManagedService.organization_id == organization_id,
                    Agent.organization_id == organization_id,
                )
                .order_by(ServiceInstance.id)
                .limit(2)
            )
        ).all()
    )
    if len(instances) != 1:
        return False
    deployment = await session.scalar(
        select(DeploymentVersion)
        .where(DeploymentVersion.instance_id == instances[0].id)
        .order_by(DeploymentVersion.recorded_at.desc(), DeploymentVersion.id.desc())
        .limit(1)
    )
    if (
        deployment is None
        or deployment.repository_id != item.repository_id
        or deployment.commit_sha != item.deployment_commit_sha
        or deployment_relation(deployment.commit_sha, item.repository_commit_sha)
        != item.deployment_relation
    ):
        return False
    current_file = await session.scalar(
        select(GitHubRepositoryFile)
        .join(Repository, Repository.id == GitHubRepositoryFile.repository_id)
        .join(
            GitHubRepositoryBinding,
            GitHubRepositoryBinding.repository_id == Repository.id,
        )
        .where(
            GitHubRepositoryFile.id == item.repository_file_id,
            GitHubRepositoryFile.repository_id == item.repository_id,
            GitHubRepositoryFile.commit_sha == item.repository_commit_sha,
            GitHubRepositoryFile.path == item.path,
            GitHubRepositoryFile.content_sha256 == item.content_sha256,
            Repository.organization_id == organization_id,
            Repository.full_name == item.full_name,
            GitHubRepositoryBinding.installation_id == settings.github_app_installation_id,
            GitHubRepositoryBinding.enabled.is_(True),
            GitHubRepositoryBinding.last_error.is_(None),
            GitHubRepositoryBinding.head_sha == item.repository_commit_sha,
        )
    )
    return current_file is not None


async def repository_snapshot_item_is_current(
    session: AsyncSession,
    repository_id: str,
    organization_id: str,
    item: RepositoryKnowledgeItem,
    settings: Settings,
) -> bool:
    if (
        not settings.conversation_repository_chat_enabled
        or item.basis != "snapshot"
        or item.repository_id != repository_id
        or item.deployment_commit_sha is not None
        or item.deployment_relation != "unknown"
    ):
        return False
    state = await repository_snapshot_state(
        session,
        repository_id,
        organization_id,
        settings,
    )
    if (
        state is None
        or not state.available
        or state.binding is None
        or state.binding.head_sha != item.repository_commit_sha
    ):
        return False
    current_file = await session.scalar(
        select(GitHubRepositoryFile)
        .join(Repository, Repository.id == GitHubRepositoryFile.repository_id)
        .where(
            GitHubRepositoryFile.id == item.repository_file_id,
            GitHubRepositoryFile.repository_id == repository_id,
            GitHubRepositoryFile.commit_sha == item.repository_commit_sha,
            GitHubRepositoryFile.path == item.path,
            GitHubRepositoryFile.content_sha256 == item.content_sha256,
            Repository.organization_id == organization_id,
            Repository.full_name == item.full_name,
        )
    )
    return current_file is not None
