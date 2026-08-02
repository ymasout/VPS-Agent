# Licensing

VPS Agent uses component-scoped licensing inside one monorepo:

- The control plane and all files not explicitly listed below are licensed under `AGPL-3.0-only`.
- `apps/agent/**`, `scripts/agent_upgrade.py`, `scripts/install-agent.sh`, and
  `.github/workflows/release-agent.yml` are licensed under `Apache-2.0`.
- Third-party dependencies remain under their respective licenses and are not relicensed by this project.

The machine-readable mapping is authoritative and is stored in `REUSE.toml`. Canonical license texts are stored in `LICENSES/`. The root `LICENSE` contains the default AGPL license, while `apps/agent/LICENSE` contains the Agent's Apache license.

Do not copy AGPL-covered control-plane code into the Apache-covered Agent without first resolving the resulting license boundary. Network communication through the documented Agent protocol does not by itself change either component's declared license.
