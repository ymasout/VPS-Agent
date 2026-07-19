import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.alerts import (
    agent_availability_fingerprint,
    evaluate_agent_availability,
    evaluate_service_alerts,
    service_is_problem,
)
from app.models import Agent, AlertEvent, ServiceStatus
from app.schemas import AgentReport, Metrics, ServiceReport


def agent() -> Agent:
    return Agent(
        id="agent-01",
        credential_hash="hash",
        name="test-vps",
        hostname="vm-01",
        machine_id="machine-01",
        os="Ubuntu",
        arch="amd64",
        version="0.2.4",
        capabilities=[],
    )


def service(state: str, healthy: bool | None) -> ServiceReport:
    return ServiceReport(
        kind="systemd",
        key="api.service",
        name="API service",
        state=state,
        detail=f"service is {state}",
        healthy=healthy,
    )


def report(item: ServiceReport | None) -> AgentReport:
    return AgentReport(
        hostname="vm-01",
        version="0.2.4",
        capabilities=[],
        collected_at=datetime.now(timezone.utc),
        metrics=Metrics(
            cpu_percent=10,
            memory_percent=20,
            memory_used_bytes=1,
            memory_total_bytes=2,
            disks=[],
        ),
        services=[] if item is None else [item],
    )


def session_with(events: list[AlertEvent]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = events
    session.scalars.return_value = result
    session.add = MagicMock()
    session.add_all = MagicMock()
    return session


def test_service_problem_classification_matches_m1_status_semantics() -> None:
    assert service_is_problem(service("failed", None))
    assert service_is_problem(service("active", False))
    assert not service_is_problem(service("inactive", None))
    assert service_is_problem(ServiceReport(kind="docker", key="web", name="web", state="exited"))


def test_offline_agent_fires_once_and_uses_machine_scope() -> None:
    observed_at = datetime.now(timezone.utc)
    current_agent = agent()
    current_agent.last_seen_at = observed_at - timedelta(minutes=2)
    session = AsyncMock()
    session.scalar.return_value = None
    session.add = MagicMock()
    session.add_all = MagicMock()

    deliveries = asyncio.run(
        evaluate_agent_availability(
            session,
            current_agent,
            observed_at,
            online=False,
            offline_after_seconds=90,
        )
    )

    event = session.add.call_args.args[0]
    assert event.source == "agent"
    assert event.service_kind is None
    assert event.service_key is None
    assert event.status == "firing"
    assert event.active_key == agent_availability_fingerprint(current_agent.id)
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "firing"
    assert deliveries[0].sequence == 1


def test_repeated_offline_scan_does_not_repeat_notification() -> None:
    observed_at = datetime.now(timezone.utc)
    current_agent = agent()
    fingerprint = agent_availability_fingerprint(current_agent.id)
    event = AlertEvent(
        id="event-01",
        agent_id=current_agent.id,
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="agent",
        title="test-vps: Agent 失联",
        severity="critical",
        status="firing",
        observation_count=1,
        notification_sequence=1,
        first_observed_at=observed_at - timedelta(minutes=1),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(minutes=1),
    )
    session = AsyncMock()
    session.scalar.return_value = event
    session.add_all = MagicMock()

    deliveries = asyncio.run(
        evaluate_agent_availability(
            session,
            current_agent,
            observed_at,
            online=False,
            offline_after_seconds=90,
        )
    )

    assert event.observation_count == 2
    assert event.status == "firing"
    assert deliveries == []


def test_agent_report_resolves_offline_event_with_sequence_two() -> None:
    observed_at = datetime.now(timezone.utc)
    current_agent = agent()
    fingerprint = agent_availability_fingerprint(current_agent.id)
    event = AlertEvent(
        id="event-01",
        agent_id=current_agent.id,
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="agent",
        title="test-vps: Agent 失联",
        severity="critical",
        status="firing",
        observation_count=3,
        notification_sequence=1,
        first_observed_at=observed_at - timedelta(minutes=3),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(minutes=3),
    )
    session = AsyncMock()
    session.scalar.return_value = event
    session.add_all = MagicMock()

    deliveries = asyncio.run(
        evaluate_agent_availability(
            session,
            current_agent,
            observed_at,
            online=True,
            offline_after_seconds=90,
        )
    )

    assert event.status == "resolved"
    assert event.active_key is None
    assert event.resolved_at == observed_at
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "resolved"
    assert deliveries[0].sequence == 2


def test_first_problem_observation_creates_pending_event_without_notification() -> None:
    session = session_with([])
    observed_at = datetime.now(timezone.utc)

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(service("failed", False)), observed_at, 2)
    )

    event = session.add.call_args.args[0]
    assert event.status == "pending"
    assert event.observation_count == 1
    assert event.active_key == event.fingerprint
    assert deliveries == []


def test_second_problem_observation_fires_once() -> None:
    observed_at = datetime.now(timezone.utc)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint="placeholder",
        active_key="placeholder",
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="pending",
        observation_count=1,
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
    item = service("failed", False)
    from app.alerts import service_fingerprint

    current.fingerprint = service_fingerprint("agent-01", item)
    current.active_key = current.fingerprint
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(item), observed_at, 2)
    )

    assert current.status == "firing"
    assert current.observation_count == 2
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "firing"


def test_healthy_observation_resolves_firing_event_and_notifies() -> None:
    observed_at = datetime.now(timezone.utc)
    item = service("active", True)
    from app.alerts import service_fingerprint

    fingerprint = service_fingerprint("agent-01", item)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="firing",
        observation_count=2,
        first_observed_at=observed_at,
        last_observed_at=observed_at,
        firing_at=observed_at,
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(item), observed_at, 2)
    )

    assert current.status == "resolved"
    assert current.active_key is None
    assert current.resolved_at == observed_at
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "resolved"


def test_healthy_observation_clears_silence_when_resolving() -> None:
    observed_at = datetime.now(timezone.utc)
    item = service("active", True)
    from app.alerts import service_fingerprint

    fingerprint = service_fingerprint("agent-01", item)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="silenced",
        observation_count=3,
        notification_sequence=1,
        first_observed_at=observed_at - timedelta(hours=1),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(hours=1),
        silenced_until=observed_at + timedelta(minutes=30),
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(item), observed_at, 2)
    )

    assert current.status == "resolved"
    assert current.silenced_until is None
    assert current.active_key is None
    assert current.resolved_at == observed_at
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "resolved"
    assert deliveries[0].sequence == 2


def test_missing_service_is_not_treated_as_recovery() -> None:
    observed_at = datetime.now(timezone.utc)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint="fingerprint",
        active_key="fingerprint",
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="firing",
        observation_count=2,
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(None), observed_at, 2)
    )

    assert current.status == "firing"
    assert deliveries == []


def test_expired_silence_refires_once_when_problem_continues() -> None:
    observed_at = datetime.now(timezone.utc)
    item = service("failed", False)
    from app.alerts import service_fingerprint

    fingerprint = service_fingerprint("agent-01", item)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="silenced",
        observation_count=3,
        notification_sequence=1,
        first_observed_at=observed_at - timedelta(hours=2),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(hours=2),
        silenced_until=observed_at - timedelta(seconds=1),
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(item), observed_at, 2)
    )

    assert current.status == "firing"
    assert current.silenced_until is None
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "firing"
    assert deliveries[0].sequence == 2


def test_unexpired_silence_stays_silent_when_problem_continues() -> None:
    observed_at = datetime.now(timezone.utc)
    item = service("failed", False)
    from app.alerts import service_fingerprint

    fingerprint = service_fingerprint("agent-01", item)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint=fingerprint,
        active_key=fingerprint,
        source="service",
        service_kind="systemd",
        service_key="api.service",
        title="API failed",
        severity="critical",
        status="silenced",
        observation_count=3,
        notification_sequence=1,
        first_observed_at=observed_at - timedelta(hours=1),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(hours=1),
        silenced_until=observed_at + timedelta(minutes=30),
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(session, agent(), report(item), observed_at, 2)
    )

    assert current.status == "silenced"
    assert current.silenced_until == observed_at + timedelta(minutes=30)
    assert deliveries == []


def test_docker_identity_upgrade_migrates_and_resolves_existing_event() -> None:
    observed_at = datetime.now(timezone.utc)
    previous = ServiceStatus(
        agent_id="agent-01",
        kind="docker",
        service_key="a1b2c3d4e5f6",
        name="api",
        state="exited",
        observed_at=observed_at - timedelta(minutes=1),
    )
    old_item = ServiceReport(kind="docker", key=previous.service_key, name="api", state="exited")
    from app.alerts import service_fingerprint

    old_fingerprint = service_fingerprint("agent-01", old_item)
    current = AlertEvent(
        id="event-01",
        agent_id="agent-01",
        fingerprint=old_fingerprint,
        active_key=old_fingerprint,
        source="service",
        service_kind="docker",
        service_key=previous.service_key,
        title="API failed",
        severity="critical",
        status="firing",
        observation_count=2,
        first_observed_at=observed_at - timedelta(minutes=2),
        last_observed_at=observed_at - timedelta(minutes=1),
        firing_at=observed_at - timedelta(minutes=1),
    )
    stable_item = ServiceReport(
        kind="docker", key="compose:payments:api:1", name="api", state="running", healthy=True
    )
    session = session_with([current])

    deliveries = asyncio.run(
        evaluate_service_alerts(
            session,
            agent(),
            report(stable_item),
            observed_at,
            2,
            [previous],
        )
    )

    assert current.service_key == stable_item.key
    assert current.fingerprint == service_fingerprint("agent-01", stable_item)
    assert current.status == "resolved"
    assert len(deliveries) == 1
    assert deliveries[0].notification_type == "resolved"
