import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.diagnostics import collect_control_plane_evidence, finalize_diagnostic
from app.models import (
    Agent,
    AlertEvent,
    DeploymentVersion,
    DiagnosticCitation,
    DiagnosticRun,
    EvidenceItem,
    GitHubRepositoryBinding,
    GitHubRepositoryFile,
    ManagedService,
    Operation,
    Repository,
    ServiceInstance,
    ServiceStatus,
)

POSTGRES_URL = os.getenv("M3_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set M3_TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)


def test_repository_snapshot_enters_m3_diagnostic_and_is_cited() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        suffix = uuid4().hex[:12]
        agent = Agent(
            id=str(uuid4()),
            organization_id="local",
            credential_hash=f"m3-closeout-credential-{suffix}",
            name="m3-closeout-agent",
            hostname=f"m3-closeout-{suffix}",
            machine_id=f"m3-closeout-machine-{suffix}",
            os="linux",
            arch="amd64",
            version="v0.4.2",
            capabilities=[],
            last_seen_at=now,
        )
        service = ManagedService(
            id=str(uuid4()),
            organization_id="local",
            name=f"m3-closeout-service-{suffix}",
            environment="production",
            criticality="non_critical",
        )
        repository = Repository(
            id=str(uuid4()),
            organization_id="local",
            full_name=f"example/m3-closeout-{suffix}",
            default_branch="main",
        )
        instance = ServiceInstance(
            id=str(uuid4()),
            service_id=service.id,
            agent_id=agent.id,
            service_kind="docker",
            service_key=f"compose:m3-closeout-{suffix}:api:1",
            deployment_directory="/opt/m3-closeout",
        )
        status = ServiceStatus(
            id=str(uuid4()),
            agent_id=agent.id,
            kind=instance.service_kind,
            service_key=instance.service_key,
            name=service.name,
            state="unhealthy",
            detail="bounded",
            healthy=False,
            observed_at=now,
        )
        event = AlertEvent(
            id=str(uuid4()),
            organization_id="local",
            agent_id=agent.id,
            fingerprint=uuid4().hex,
            source="service",
            service_kind=instance.service_kind,
            service_key=instance.service_key,
            title="M3 repository evidence canary",
            severity="critical",
            status="firing",
            observation_count=2,
            first_observed_at=now,
            last_observed_at=now,
        )
        deployment = DeploymentVersion(
            id=str(uuid4()),
            instance_id=instance.id,
            repository_id=repository.id,
            commit_sha="a" * 40,
            recorded_at=now,
        )
        binding = GitHubRepositoryBinding(
            id=str(uuid4()),
            repository_id=repository.id,
            installation_id=1,
            github_repository_id=int(suffix[:8], 16),
            private=True,
            enabled=True,
            head_sha="a" * 40,
            synchronized_at=now,
        )
        repository_file = GitHubRepositoryFile(
            id=str(uuid4()),
            repository_id=repository.id,
            commit_sha="a" * 40,
            path="README.md",
            content="service documentation password=closeout-secret",
            content_sha256="b" * 64,
            byte_size=46,
            redacted=False,
            truncated=False,
            fetched_at=now,
        )
        diagnostic = DiagnosticRun(
            id=str(uuid4()),
            organization_id="local",
            event_id=event.id,
            instance_id=instance.id,
            status="pending",
            trigger="manual",
            provider="deterministic",
            created_at=now,
        )

        async with factory() as session:
            session.add_all([agent, service, repository])
            await session.commit()
            session.add_all([instance, status, binding, repository_file])
            await session.commit()
            session.add_all([event, deployment])
            await session.commit()
            session.add(diagnostic)
            await session.commit()
            operations_before = int(
                await session.scalar(select(func.count()).select_from(Operation)) or 0
            )

            await collect_control_plane_evidence(
                session, diagnostic, event, instance, Settings()
            )
            await session.commit()
            repository_evidence = await session.scalar(
                select(EvidenceItem).where(
                    EvidenceItem.diagnostic_id == diagnostic.id,
                    EvidenceItem.evidence_type == "repository_file",
                )
            )
            assert repository_evidence is not None
            assert repository_evidence.source_metadata["path"] == "README.md"
            assert "closeout-secret" not in repository_evidence.content

            await finalize_diagnostic(session, diagnostic, Settings())
            await session.commit()
            await session.refresh(diagnostic)
            assert diagnostic.status == "completed"
            assert any(
                repository_evidence.id in item["evidence_ids"]
                for item in diagnostic.result["facts"]
            )
            citation = await session.scalar(
                select(DiagnosticCitation).where(
                    DiagnosticCitation.diagnostic_id == diagnostic.id,
                    DiagnosticCitation.evidence_id == repository_evidence.id,
                )
            )
            assert citation is not None
            assert (
                int(await session.scalar(select(func.count()).select_from(Operation)) or 0)
                == operations_before
            )

        async with factory() as session:
            await session.execute(delete(Agent).where(Agent.id == agent.id))
            await session.execute(
                delete(ManagedService).where(ManagedService.id == service.id)
            )
            await session.execute(
                delete(Repository).where(Repository.id == repository.id)
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(scenario())
