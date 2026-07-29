# Security Policy

## Supported versions

Until the first formal control-plane release, only the current `main` branch and the newest Agent release are eligible for security fixes. Older development snapshots are unsupported.

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, private infrastructure data, database contents, signed task material, Agent identity files, notification URLs, or reproduction steps that could endanger a running instance.

GitHub private vulnerability reporting is the intended reporting channel, but it is not enabled yet. Enabling and testing that channel is a release blocker. Until it is enabled, do not claim that the project has a confidential vulnerability-reporting path and do not publish a security-sensitive release.

Never attach production `.env` files, backups, logs, database dumps, operation signatures, GitHub App keys, Provider keys, Telegram tokens, DingTalk webhook URLs, or Agent credentials to a report.

## Security boundaries

- Agents initiate outbound connections; the control plane does not SSH into managed VPS hosts.
- Operations require explicit server authorization, confirmation, signed expiring tasks, nonce/idempotency checks, Agent capability policy, health verification, and audit.
- Natural-language or model output never grants write authority.
- Free-form shell, arbitrary paths, automatic confirmation, automatic execution, and automatic rollback are not supported.
- SaaS, multi-tenancy, public registration, GitHub write, Runbook execution, and Web SSH remain out of scope.

## Disclosure

Coordinate remediation and release timing before public disclosure. Acknowledgement or bounty is not guaranteed. Never test against infrastructure you do not own or have explicit permission to assess.
