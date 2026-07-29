# Copyright and provenance audit

Audit date: 2026-07-30

## Repository evidence

- Git history at the audit point contains 80 commits authored as `YY Home <ymasout@gmail.com>` and one commit authored by the production host identity `root <root@ser549696707335.local>`.
- The production-host commit `f7463a66b07e3dd835951f24f6d68d39877ce1ce` only added `.env.production` to `.gitignore`; it introduced no source code or third-party content.
- The repository has no Git submodules and no tracked `node_modules`, Python virtual environment, compiled `dist`, database, backup, private-key, or production `.env` artifact.
- Python, Node, Go and container dependencies are referenced as external packages/images and retain their own licenses. They are not covered by the project copyright statement.
- Tests contain deliberately fake secret-shaped strings for redaction checks; these are project-authored fixtures, not production credentials.

## What the repository cannot prove

Git metadata cannot prove employment, commissioning, assignment, prior unpublished authorship, or whether any code was copied without attribution before it entered history. The repository owner must personally confirm those facts.

## Owner attestation

On 2026-07-30, the repository owner explicitly confirmed all of the following:

1. They own, or have authority to license, all project-authored code, documentation, configuration and assets in the declared scopes.
2. No employer, client, contractor, collaborator, previous project, code generator, or private repository retains conflicting rights.
3. Any AI-assisted output was reviewed and is not knowingly copied from a restricted source.
4. The copyright name `YY Home` is the intended public rights holder identity.
5. They accept `AGPL-3.0-only` for the default/control-plane scope and `Apache-2.0` for the Agent scope.

Automated CI can verify provenance indicators and third-party dependency metadata, but it cannot replace this legal attestation or professional legal review.

Status: **recorded**. This closes the project-owner rights-confirmation gate for
M6.4a. It is a project record, not an independent legal opinion.
