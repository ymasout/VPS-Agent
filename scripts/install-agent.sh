#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${VPS_AGENT_REPOSITORY:-ymasout/VPS-Agent}"
VERSION="latest"
DOWNLOAD_BASE_URL="${VPS_AGENT_DOWNLOAD_BASE_URL:-}"
CONTROL_PLANE_URL=""
AGENT_NAME=""
REGISTRATION_TOKEN="${AGENT_REGISTRATION_TOKEN:-}"
HEALTHCHECK_URLS=""
REPORT_INTERVAL=""
EVIDENCE_POLICY=""
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/vps-agent"
DATA_DIR="/var/lib/vps-agent"

usage() {
  cat <<'EOF'
Usage: sudo ./install-agent.sh --url URL [options]

Options:
  --url URL             Control plane URL, for example https://ops.example.com
  --name NAME           Name shown in Fleet (defaults to hostname)
  --token TOKEN         One-time registration token (interactive prompt recommended)
  --healthcheck URLS    Comma-separated HTTP healthcheck URLs
  --interval DURATION   Report interval (default: 30s)
  --evidence-policy POLICY  Evidence policy: disabled, docker-logs, systemd-journal, or docker-systemd
  --version VERSION     Release version such as 0.2.2 (default: latest)
  --download-base-url URL  Optional control-plane download mirror
  -h, --help            Show this help

Existing installations keep their identity and do not need another token.
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) CONTROL_PLANE_URL="${2:-}"; shift 2 ;;
    --name) AGENT_NAME="${2:-}"; shift 2 ;;
    --token) REGISTRATION_TOKEN="${2:-}"; shift 2 ;;
    --healthcheck) HEALTHCHECK_URLS="${2:-}"; shift 2 ;;
    --interval) REPORT_INTERVAL="${2:-}"; shift 2 ;;
    --evidence-policy) EVIDENCE_POLICY="${2:-}"; shift 2 ;;
    --version) VERSION="${2:-}"; shift 2 ;;
    --download-base-url) DOWNLOAD_BASE_URL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "run this installer with sudo or as root"
[[ "$(uname -s)" == "Linux" ]] || fail "only Linux is supported"
command -v systemctl >/dev/null || fail "systemd is required"
command -v curl >/dev/null || fail "curl is required"
command -v sha256sum >/dev/null || fail "sha256sum is required"

case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

ENV_FILE="${CONFIG_DIR}/agent.env"
IDENTITY_FILE="${DATA_DIR}/identity.json"
MACHINE_ID_FILE="${DATA_DIR}/machine-id"

existing_value() {
  local key="$1"
  [[ -f "${ENV_FILE}" ]] || return 0
  sed -n "s/^${key}=//p" "${ENV_FILE}" | head -n1
}

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-$(existing_value CONTROL_PLANE_URL)}"
AGENT_NAME="${AGENT_NAME:-$(existing_value AGENT_NAME)}"
HEALTHCHECK_URLS="${HEALTHCHECK_URLS:-$(existing_value AGENT_HEALTHCHECK_URLS)}"
REPORT_INTERVAL="${REPORT_INTERVAL:-$(existing_value AGENT_REPORT_INTERVAL)}"
EVIDENCE_POLICY="${EVIDENCE_POLICY:-$(existing_value AGENT_EVIDENCE_POLICY)}"
EVIDENCE_SOURCES_JSON="${AGENT_EVIDENCE_SOURCES_JSON:-$(existing_value AGENT_EVIDENCE_SOURCES_JSON)}"
AGENT_NAME="${AGENT_NAME:-$(hostname 2>/dev/null || printf 'VPS Agent')}"
REPORT_INTERVAL="${REPORT_INTERVAL:-30s}"
EVIDENCE_POLICY="${EVIDENCE_POLICY:-disabled}"

for value in "${CONTROL_PLANE_URL}" "${AGENT_NAME}" "${HEALTHCHECK_URLS}" "${REPORT_INTERVAL}" "${EVIDENCE_POLICY}" "${EVIDENCE_SOURCES_JSON}"; do
  [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || fail "configuration values cannot contain newlines"
done
[[ "${CONTROL_PLANE_URL}" =~ ^https:// ]] || fail "--url must use HTTPS"
case "${EVIDENCE_POLICY}" in
  disabled) AGENT_EVIDENCE_POLICY="disabled" ;;
  docker-logs|docker_logs) AGENT_EVIDENCE_POLICY="docker_logs" ;;
  systemd-journal|systemd_journal) AGENT_EVIDENCE_POLICY="systemd_journal" ;;
  docker-systemd|docker_logs,systemd_journal) AGENT_EVIDENCE_POLICY="docker_logs,systemd_journal" ;;
  *) fail "--evidence-policy must be disabled, docker-logs, systemd-journal, or docker-systemd" ;;
esac

if [[ ! -f "${IDENTITY_FILE}" && -z "${REGISTRATION_TOKEN}" ]]; then
  [[ -r /dev/tty ]] || fail "a registration token is required for first installation"
  read -r -s -p "Registration token: " REGISTRATION_TOKEN </dev/tty
  printf '\n' >/dev/tty
fi
if [[ ! -f "${IDENTITY_FILE}" ]]; then
  [[ "${REGISTRATION_TOKEN}" == reg_* ]] || fail "registration token must start with reg_"
fi

if [[ -n "${DOWNLOAD_BASE_URL}" ]]; then
  [[ "${DOWNLOAD_BASE_URL}" =~ ^https:// ]] || fail "--download-base-url must use HTTPS"
  if [[ "${VERSION}" == "latest" ]]; then
    BASE_URL="${DOWNLOAD_BASE_URL%/}/latest"
  else
    VERSION="${VERSION#v}"
    BASE_URL="${DOWNLOAD_BASE_URL%/}/v${VERSION}"
  fi
elif [[ "${VERSION}" == "latest" ]]; then
  BASE_URL="https://github.com/${REPOSITORY}/releases/latest/download"
else
  VERSION="${VERSION#v}"
  BASE_URL="https://github.com/${REPOSITORY}/releases/download/v${VERSION}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
BINARY="vps-agent-linux-${ARCH}"
printf 'Downloading VPS Agent (%s)...\n' "${ARCH}"
curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error "${BASE_URL}/${BINARY}" -o "${TMP_DIR}/${BINARY}"
curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error "${BASE_URL}/SHA256SUMS" -o "${TMP_DIR}/SHA256SUMS"
(
  cd "${TMP_DIR}"
  grep " ${BINARY}$" SHA256SUMS | sha256sum --check --status -
) || fail "binary checksum verification failed"

install -d -m 0755 "${INSTALL_DIR}" "${CONFIG_DIR}"
install -d -m 0700 "${DATA_DIR}"
if [[ ! -f "${MACHINE_ID_FILE}" ]]; then
  if [[ -f "${IDENTITY_FILE}" && -r /etc/machine-id ]]; then
    tr -d '\n' </etc/machine-id >"${MACHINE_ID_FILE}"
  else
    [[ -r /proc/sys/kernel/random/uuid ]] || fail "kernel UUID generator is unavailable"
    tr -d '\n' </proc/sys/kernel/random/uuid >"${MACHINE_ID_FILE}"
  fi
  chmod 0600 "${MACHINE_ID_FILE}"
fi
systemctl stop vps-agent.service 2>/dev/null || true
install -m 0755 "${TMP_DIR}/${BINARY}" "${INSTALL_DIR}/vps-agent"

umask 077
{
  printf 'CONTROL_PLANE_URL=%s\n' "${CONTROL_PLANE_URL}"
  printf 'AGENT_NAME=%s\n' "${AGENT_NAME}"
  printf 'AGENT_CREDENTIAL_FILE=%s\n' "${IDENTITY_FILE}"
  if [[ -f "${MACHINE_ID_FILE}" ]]; then
    printf 'AGENT_MACHINE_ID=%s\n' "$(cat "${MACHINE_ID_FILE}")"
  fi
  printf 'AGENT_REPORT_INTERVAL=%s\n' "${REPORT_INTERVAL}"
  printf 'AGENT_HEALTHCHECK_URLS=%s\n' "${HEALTHCHECK_URLS}"
  printf 'AGENT_EVIDENCE_POLICY=%s\n' "${AGENT_EVIDENCE_POLICY}"
  printf 'AGENT_EVIDENCE_SOURCES_JSON=%s\n' "${EVIDENCE_SOURCES_JSON:-[]}"
  if [[ ! -f "${IDENTITY_FILE}" ]]; then
    printf 'AGENT_REGISTRATION_TOKEN=%s\n' "${REGISTRATION_TOKEN}"
  fi
} >"${ENV_FILE}"
chmod 0600 "${ENV_FILE}"

cat > /etc/systemd/system/vps-agent.service <<'EOF'
[Unit]
Description=AI VPS Operations Agent
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/vps-agent/agent.env
ExecStart=/usr/local/bin/vps-agent
Restart=always
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/vps-agent

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now vps-agent.service

if [[ ! -f "${IDENTITY_FILE}" ]]; then
  for _ in {1..15}; do
    [[ -f "${IDENTITY_FILE}" ]] && break
    sleep 2
  done
  if [[ -f "${IDENTITY_FILE}" ]]; then
    sed -i '/^AGENT_REGISTRATION_TOKEN=/d' "${ENV_FILE}"
    systemctl restart vps-agent.service
  else
    journalctl -u vps-agent.service -n 20 --no-pager >&2 || true
    fail "agent did not register; inspect the service logs above"
  fi
fi

REGISTRATION_TOKEN=""
printf '\nInstalled %s\n' "$("${INSTALL_DIR}/vps-agent" --version)"
printf 'Service: systemctl status vps-agent --no-pager\n'
printf 'Logs:    journalctl -u vps-agent -f\n'
