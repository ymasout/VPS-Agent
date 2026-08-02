# Formal release process

This process builds reviewable assets without granting CI authority to deploy a control plane.

## Required approvals

1. Implement, test and independently audit the committed release candidate.
2. Obtain explicit approval before creating the immutable Git tag and draft GitHub Release.
3. Obtain explicit approval before pushing GHCR candidates or changing package visibility. API and Web packages are
   intended to be public, but visibility is a repository-owner decision and is never changed by the workflow.
4. Verify anonymous digest pulls, signatures, provenance, SBOMs and draft assets, then obtain explicit approval to
   promote the same digests to SemVer tags and publish the Release.
5. Production upgrade is a separate approval and uses the existing preflight/backup/migrate/up/postflight chain.

## Release-only deployment transition

Existing owner deployments use `deploy/compose.production.yaml`, which builds API/Web from source. A formal release
uses that file plus `deploy/release/compose.release.yaml`; the override removes both `build` sections and requires
digest-pinned API, Web, Caddy, PostgreSQL and Redis images.

```text
COMPOSE_OVERRIDE_FILE=deploy/release/compose.release.yaml \
RELEASE_IMAGE_ENV_FILE=deploy/release/images.env \
ENV_FILE=deploy/.env.production \
sh deploy/control-plane-release.sh release-pull

COMPOSE_OVERRIDE_FILE=deploy/release/compose.release.yaml \
RELEASE_IMAGE_ENV_FILE=deploy/release/images.env \
ENV_FILE=deploy/.env.production \
sh deploy/control-plane-release.sh preflight
```

After explicit approval, run `migrate`, `release-up`, `reload-caddy`, then `postflight`. `release-up` always passes
`--no-build`; a missing image fails instead of silently rebuilding local source. The preflight backup remains mandatory.

The signed release bundle already contains a deterministically generated, non-secret `deploy/release/images.env` whose
five values match `release-manifest.json`. The v0.6.1 production canary instead created the host-local copy manually from
the same verified digests. Automatically verifying/extracting the signed bundle into a staged deployment directory is a
follow-up hardening item; until then, operators must compare all five values with the signed release manifest before
`release-check` and retain the exact file for rollback audit.

## Verification

- Verify `SHA256SUMS` and every cosign bundle against the documented GitHub workflow identity and issuer.
- Pull API/Web by digest and compare OCI version/revision labels to `release-manifest.json`.
- Confirm `/healthz` stays minimal and managed `system-info` reports the release commit and current schema.
- Run backup → empty isolated restore → schema check → key-table count comparison before production authorization.

Candidate tags are never referenced by release Compose or installation documentation. Failed candidates are retained or
removed only after an explicit audit decision; an existing SemVer Git or image tag is never moved.

GitHub Release and the two GHCR packages do not support a cross-service transaction. The publish phase therefore checks
both public candidate digests, signatures, draft state and absence of both SemVer tags before obtaining registry write
credentials. If an external failure still leaves only one SemVer image tag, the GitHub Release remains draft and the
workflow stops; operators must treat this as a release incident, audit the registry state and obtain explicit cleanup or
recovery authorization. The workflow never retries by moving an existing SemVer tag.
