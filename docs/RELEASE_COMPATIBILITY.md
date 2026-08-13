# Release compatibility matrix

The matrix is fail-closed: a version is supported only after the listed path has passed automated and isolated
integration tests. Historical documentation is not compatibility evidence.

| Release path | Database | Agent | Status |
|---|---|---|---|
| Clean install `v0.6.1` | Empty PostgreSQL 16 → `0020_m6_named_approval` | `v0.6.1` amd64/arm64 | Passed (formal release 2026-08-01) |
| Previous production baseline `0d75342` → `v0.6.1` | Revision `0020_m6_named_approval` (no-op migration) | Existing `v0.4.2` | **Passed** (production upgrade canary 2026-08-01) |
| Production `v0.6.3` (`7c1d2b2`) → `v0.6.5` | Revision `0020_m6_named_approval` (no-op migration) | Unchanged | **Passed** (production upgrade canary 2026-08-13) |
| Agent `v0.4.2` → `v0.6.5` transactional upgrade | Not applicable | `v0.6.5` amd64 | **Passed** (production canary 2026-08-13) |
| Agent upgrade failure rollback | Not applicable | Previous generation restored | **Passed** (real systemd CI end-to-end); production separately verified unsupported-path fail-closed before change (2026-08-13) |
| Application rollback | Remains at `0020_m6_named_approval` | Unchanged | Only to the recorded compatible previous image digest |
| Backup restore | Exact manifest version/revision and PostgreSQL major | Not applicable | Offline isolated target only |

Agent `v0.4.2` remains supported only for existing report, evidence, restart and Compose deploy protocol behavior
covered by the compatibility suite. Versions older than `v0.4.2` are unsupported until separately tested.

The release bundle never performs an automatic database restore, capability expansion, rollback or production upgrade.
