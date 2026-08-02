# Changelog

This changelog records user-visible changes for the first unified VPS Agent release. Historical Agent-only
tags remain available; `v0.6.1` is the first formal monorepo release covering the control plane and Agent.

## [0.6.2] - 2026-08-02

### Agent transactional upgrade and release security hardening

- Added transactional Agent upgrade with process lock, previous generation, durable
  journal, 30-second stability window, automatic rollback on failure and cross-boot recovery.
- Added signed `agent-upgrade.json` metadata with strict version compatibility gate.
- Added safe release bundle staging CLI with archive path traversal defense and
  images.env/manifest consistency verification.
- Added Dependabot, three-language CodeQL, OSV-Scanner dependency gate and multi-arch
  Trivy OCI vulnerability scanning to the formal release pipeline.
- Upgraded FastAPI, Alembic, PyJWT and pinned transitive dependencies.

## [0.6.1] - 2026-08-01

### M0–M2: self-hosted operations foundation

- Added the API, Web console, PostgreSQL/Redis control plane and outbound-only Agent registration/reporting.
- Added service discovery, health monitoring, alert deduplication, DingTalk notifications and recovery events.
- Added credential redaction, bounded evidence collection and production deployment checks.

### M3: diagnostics

- Added deterministic and explicitly configured HTTP diagnostic providers with structured evidence citations.
- Added bounded Docker/systemd evidence, GitHub App read-only repository snapshots and fail-closed provider errors.

### M4: controlled operations

- Added explicit restart, digest-pinned Compose deploy and user-initiated rollback plans.
- Preserved confirmation, Ed25519 signatures, expiry, nonce/idempotency, Agent capability policy, health verification
  and immutable audit transitions throughout the execution chain.

### M5: conversation experience

- Added scoped conversations for events, repositories, machines and services, plus feedback, fleet summaries,
  read-only operation timelines and non-executable Runbook drafts.
- Conversation output remains advisory and cannot directly acquire write authority.

### M6: self-hosted productization

- Added verifiable control-plane backup/isolated restore, build identity, PWA/mobile read-only views and mobile M4 approval.
- Added DingTalk and Telegram channel selection, versioned templates, notification test auditing and a reserved Feishu adapter contract.
- Added dual licensing, source-distribution and dependency-license gates, trusted Principal read capabilities and named
  maker-checker M4 approvals.
- Added a unified release specification, signed/SBOM-bearing release assets and digest-pinned release deployment mode.

### Compatibility and security notes

- Database head is `0020_m6_named_approval`; downgrade remains fail-closed when named actor snapshots exist.
- Agent `v0.4.2` is the oldest initially supported Agent and must be validated by the release compatibility workflow.
- Web SSH, arbitrary Shell, automatic confirmation/execution/rollback, SaaS and multi-tenancy remain out of scope.

[0.6.1]: https://github.com/ymasout/VPS-Agent/releases/tag/v0.6.1
