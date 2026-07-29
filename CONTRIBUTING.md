# Contributing

Thank you for helping improve VPS Agent. Contributions must preserve the self-hosted, least-authority design and the component license boundary.

## Before opening a change

1. Discuss large features and all security-boundary changes before implementation.
2. Do not include credentials, production data, backups, private logs, database dumps, generated build output, or copied third-party source.
3. Keep the control plane and Agent license scopes defined in `LICENSING.md` and `REUSE.toml`.
4. State the origin and license of any imported code, asset, schema, template, or generated file.

## Development checks

Run the repository checks appropriate to the change:

```text
make check
python scripts/source_release.py check
python scripts/dependency_licenses.py --output dist/dependency-licenses.json
```

Database changes additionally require a single Alembic head, both-direction offline SQL where supported, and real PostgreSQL migration tests. Web standalone packaging changes require the real image CI gate. Agent changes require `go test ./...` and `go vet ./...`.

## Security invariants

Contributions must not introduce free shell execution, arbitrary paths, client-asserted trusted actors, automatic confirmation/execution/rollback, direct Web/API connections to VPS hosts, or model-controlled write authority. M4 operations must continue to use plan, confirmation, signature, claim, execution, health verification, and audit.

## Licensing contributions

By submitting a contribution, you certify that you have the right to submit it under the license assigned to its target files:

- control plane/default scope: `AGPL-3.0-only`;
- Agent scope: `Apache-2.0`.

This repository does not currently require a CLA. If future commercial dual licensing is proposed, contributor-rights handling must be decided before accepting contributions under that model; it must not be applied retroactively by assumption.
