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
OPERATION_POLICY=""
OPERATION_KEY_ID=""
OPERATION_PUBLIC_KEY=""
DEPLOY_POLICY=""
DEPLOY_ALLOWED_ROOT=""
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/vps-agent"
DATA_DIR="/var/lib/vps-agent"
ALLOW_LEGACY_CHECKSUM_ONLY="false"
COSIGN_CERTIFICATE_IDENTITY="https://github.com/ymasout/VPS-Agent/.github/workflows/formal-release.yml@refs/heads/main"
COSIGN_OIDC_ISSUER="https://token.actions.githubusercontent.com"

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
  --operation-policy POLICY  Write policy: disabled or docker-restart
  --operation-key-id ID      Ed25519 verification key identifier
  --operation-public-key KEY Base64 Ed25519 public key (required for docker-restart)
  --deploy-policy POLICY     Deploy policy: disabled, plan-only, or docker-compose-deploy
  --deploy-allowed-root DIR  Local Compose root required for docker-compose-deploy
  --version VERSION     Release version such as 0.2.2 (default: latest)
  --download-base-url URL  Optional control-plane download mirror
  --allow-legacy-checksum-only  Permit an old unsigned Agent release (unsafe compatibility escape hatch)
  -h, --help            Show this help

Existing installations keep their identity and do not need another token.
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  printf '{"audit_code":"rejected_before_change"}\n' >&2
  exit 20
}

download() {
  local url="$1"
  local output="$2"
  local label="$3"
  curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error "$url" -o "$output" || \
    fail "download failed: ${label}"
}

# Read an agent binary's version robustly. Older agents (<= 0.6.3) print
# --version to stderr (Go's built-in println); newer agents print to stdout.
# Capture both streams, require the exact single-line "vps-agent X.Y.Z" format,
# and fail closed on any other output (multi-line, warnings, bad format).
read_agent_version() {
  local binary="$1"
  local output
  if ! output="$("${binary}" --version 2>&1)"; then
    return 1
  fi
  [[ "${output}" =~ ^vps-agent\ ([0-9]+\.[0-9]+\.[0-9]+)$ ]] || return 1
  printf '%s\n' "${BASH_REMATCH[1]}"
}

# GitHub Release downloads do not preserve Unix executable mode bits. Apply
# the required mode only after checksum/signature verification and before the
# first attempt to execute the downloaded Agent binary.
prepare_downloaded_agent_binary() {
  chmod 0755 "$1"
}

# Hidden self-test hook for the version-detection regression test. Not a user
# interface; not documented; subject to change without notice.
if [[ "${1:-}" == "__selftest_read_version__" ]]; then
  if prepare_downloaded_agent_binary "${2:-}" && read_agent_version "${2:-}"; then
    exit 0
  fi
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) CONTROL_PLANE_URL="${2:-}"; shift 2 ;;
    --name) AGENT_NAME="${2:-}"; shift 2 ;;
    --token) REGISTRATION_TOKEN="${2:-}"; shift 2 ;;
    --healthcheck) HEALTHCHECK_URLS="${2:-}"; shift 2 ;;
    --interval) REPORT_INTERVAL="${2:-}"; shift 2 ;;
    --evidence-policy) EVIDENCE_POLICY="${2:-}"; shift 2 ;;
    --operation-policy) OPERATION_POLICY="${2:-}"; shift 2 ;;
    --operation-key-id) OPERATION_KEY_ID="${2:-}"; shift 2 ;;
    --operation-public-key) OPERATION_PUBLIC_KEY="${2:-}"; shift 2 ;;
    --deploy-policy) DEPLOY_POLICY="${2:-}"; shift 2 ;;
    --deploy-allowed-root) DEPLOY_ALLOWED_ROOT="${2:-}"; shift 2 ;;
    --version) VERSION="${2:-}"; shift 2 ;;
    --download-base-url) DOWNLOAD_BASE_URL="${2:-}"; shift 2 ;;
    --allow-legacy-checksum-only) ALLOW_LEGACY_CHECKSUM_ONLY="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Error: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "run this installer with sudo or as root"
[[ "$(uname -s)" == "Linux" ]] || fail "only Linux is supported"
command -v systemctl >/dev/null || fail "systemd is required"
command -v curl >/dev/null || fail "curl is required"
command -v sha256sum >/dev/null || fail "sha256sum is required"
command -v flock >/dev/null || fail "flock is required"
command -v python3 >/dev/null || fail "python3 is required"
install -d -m 0755 /run/lock
exec 9>/run/lock/vps-agent-install.lock
flock -n 9 || { printf '{"audit_code":"upgrade_locked"}\n' >&2; exit 21; }

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
OPERATION_POLICY="${OPERATION_POLICY:-$(existing_value AGENT_OPERATION_POLICY)}"
OPERATION_KEY_ID="${OPERATION_KEY_ID:-$(existing_value AGENT_OPERATION_KEY_ID)}"
OPERATION_PUBLIC_KEY="${OPERATION_PUBLIC_KEY:-$(existing_value AGENT_OPERATION_PUBLIC_KEY_BASE64)}"
DEPLOY_POLICY="${DEPLOY_POLICY:-$(existing_value AGENT_DEPLOY_POLICY)}"
DEPLOY_ALLOWED_ROOT="${DEPLOY_ALLOWED_ROOT:-$(existing_value AGENT_DEPLOY_ALLOWED_ROOTS)}"
AGENT_NAME="${AGENT_NAME:-$(hostname 2>/dev/null || printf 'VPS Agent')}"
REPORT_INTERVAL="${REPORT_INTERVAL:-30s}"
EVIDENCE_POLICY="${EVIDENCE_POLICY:-disabled}"
OPERATION_POLICY="${OPERATION_POLICY:-disabled}"
DEPLOY_POLICY="${DEPLOY_POLICY:-disabled}"

for value in "${CONTROL_PLANE_URL}" "${AGENT_NAME}" "${HEALTHCHECK_URLS}" "${REPORT_INTERVAL}" "${EVIDENCE_POLICY}" "${EVIDENCE_SOURCES_JSON}" "${OPERATION_POLICY}" "${OPERATION_KEY_ID}" "${OPERATION_PUBLIC_KEY}" "${DEPLOY_POLICY}" "${DEPLOY_ALLOWED_ROOT}"; do
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
case "${OPERATION_POLICY}" in
  disabled) AGENT_OPERATION_POLICY="disabled" ;;
  docker-restart|docker_restart) AGENT_OPERATION_POLICY="docker_restart" ;;
  *) fail "--operation-policy must be disabled or docker-restart" ;;
esac
case "${DEPLOY_POLICY}" in
  disabled) AGENT_DEPLOY_POLICY="disabled" ;;
  plan-only|plan_only) AGENT_DEPLOY_POLICY="plan_only" ;;
  docker-compose-deploy|docker_compose_deploy) AGENT_DEPLOY_POLICY="docker_compose_deploy" ;;
  *) fail "--deploy-policy must be disabled, plan-only, or docker-compose-deploy" ;;
esac
if [[ "${AGENT_OPERATION_POLICY}" == "docker_restart" || "${AGENT_DEPLOY_POLICY}" == "docker_compose_deploy" ]]; then
  [[ "${OPERATION_KEY_ID}" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || fail "--operation-key-id is required and invalid"
  [[ "${OPERATION_PUBLIC_KEY}" =~ ^[A-Za-z0-9+/]{43}=$ ]] || fail "--operation-public-key must be a Base64 Ed25519 public key"
fi
if [[ "${AGENT_DEPLOY_POLICY}" == "docker_compose_deploy" ]]; then
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || fail "docker compose is required for docker-compose-deploy"
  [[ "${DEPLOY_ALLOWED_ROOT}" == /* && -d "${DEPLOY_ALLOWED_ROOT}" ]] || fail "--deploy-allowed-root must be an existing absolute directory"
  DEPLOY_ALLOWED_ROOT="$(readlink -f -- "${DEPLOY_ALLOWED_ROOT}")"
  [[ -n "${DEPLOY_ALLOWED_ROOT}" ]] || fail "--deploy-allowed-root cannot be resolved"
else
  DEPLOY_ALLOWED_ROOT=""
fi

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
UPGRADE_HELPER="agent-upgrade.py"
UPGRADE_METADATA="agent-upgrade.json"
UPGRADE_STATE_DIR="${DATA_DIR}/upgrades"
INSTALLED_HELPER="/usr/local/libexec/vps-agent-upgrade.py"
RECOVERY_WRAPPER="/usr/local/libexec/vps-agent-upgrade-recover"
RECOVERY_UNIT="/etc/systemd/system/vps-agent-upgrade-recovery.service"
AGENT_UNIT="/etc/systemd/system/vps-agent.service"
EXISTING_INSTALL="false"
CURRENT_VERSION=""
if [[ -x "${INSTALL_DIR}/vps-agent" ]]; then
  EXISTING_INSTALL="true"
  CURRENT_VERSION="$(read_agent_version "${INSTALL_DIR}/vps-agent")" || { printf '{"audit_code":"rejected_before_change","reason":"current_version_invalid"}\n' >&2; exit 20; }
  [[ "${CURRENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf '{"audit_code":"rejected_before_change","reason":"current_version_invalid"}\n' >&2; exit 20; }
fi

if [[ -f "${UPGRADE_STATE_DIR}/transaction.json" ]]; then
  [[ -x "${INSTALLED_HELPER}" ]] || { printf '{"audit_code":"interrupted_transaction_recovery_failed"}\n' >&2; exit 32; }
  if ! python3 "${INSTALLED_HELPER}" rollback --state-dir "${UPGRADE_STATE_DIR}"; then
    printf '{"audit_code":"interrupted_transaction_recovery_failed"}\n' >&2
    exit 32
  fi
  systemctl daemon-reload
  systemctl restart vps-agent.service || { printf '{"audit_code":"interrupted_transaction_recovery_failed"}\n' >&2; exit 32; }
fi

printf 'Downloading VPS Agent (%s)...\n' "${ARCH}"
download "${BASE_URL}/${BINARY}" "${TMP_DIR}/${BINARY}" "Agent binary"
download "${BASE_URL}/SHA256SUMS" "${TMP_DIR}/SHA256SUMS" "SHA256SUMS"

if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" == "true" ]]; then
  (cd "${TMP_DIR}" && grep " ${BINARY}$" SHA256SUMS | sha256sum --check --status -) || fail "binary checksum verification failed"
  printf 'WARNING: signature verification was explicitly bypassed for a legacy release; checksum does not prove publisher identity.\n' >&2
else
  command -v cosign >/dev/null || fail "cosign is required to verify formal releases; install cosign or explicitly use --allow-legacy-checksum-only for an old release"
  for asset in "${BINARY}" "${UPGRADE_HELPER}" "${UPGRADE_METADATA}"; do
    download "${BASE_URL}/${asset}" "${TMP_DIR}/${asset}" "${asset}"
    download "${BASE_URL}/${asset}.sigstore.json" "${TMP_DIR}/${asset}.sigstore.json" "${asset} signature"
    (cd "${TMP_DIR}" && grep " ${asset}$" SHA256SUMS | sha256sum --check --status -) || fail "${asset} checksum verification failed"
    cosign verify-blob --bundle "${TMP_DIR}/${asset}.sigstore.json" \
      --certificate-identity "${COSIGN_CERTIFICATE_IDENTITY}" \
      --certificate-oidc-issuer "${COSIGN_OIDC_ISSUER}" "${TMP_DIR}/${asset}" >/dev/null || \
      fail "${asset} publisher signature verification failed"
  done
  if ! DISCOVERED_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["target_version"])' "${TMP_DIR}/${UPGRADE_METADATA}")"; then
    fail "upgrade metadata is not valid JSON"
  fi
  [[ "${DISCOVERED_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "upgrade metadata target version is invalid"
  if [[ "${VERSION}" == "latest" ]]; then
    VERSION="${DISCOVERED_VERSION}"
    if [[ -n "${DOWNLOAD_BASE_URL}" ]]; then
      BASE_URL="${DOWNLOAD_BASE_URL%/}/v${VERSION}"
    else
      BASE_URL="https://github.com/${REPOSITORY}/releases/download/v${VERSION}"
    fi
    for asset in "${BINARY}" "SHA256SUMS" "${UPGRADE_HELPER}" "${UPGRADE_METADATA}" \
      "${BINARY}.sigstore.json" "${UPGRADE_HELPER}.sigstore.json" "${UPGRADE_METADATA}.sigstore.json"; do
      download "${BASE_URL}/${asset}" "${TMP_DIR}/${asset}" "immutable ${asset}"
    done
    for asset in "${BINARY}" "${UPGRADE_HELPER}" "${UPGRADE_METADATA}"; do
      (cd "${TMP_DIR}" && grep " ${asset}$" SHA256SUMS | sha256sum --check --status -) || fail "${asset} checksum verification failed"
      cosign verify-blob --bundle "${TMP_DIR}/${asset}.sigstore.json" \
        --certificate-identity "${COSIGN_CERTIFICATE_IDENTITY}" --certificate-oidc-issuer "${COSIGN_OIDC_ISSUER}" \
        "${TMP_DIR}/${asset}" >/dev/null || fail "${asset} publisher signature verification failed"
    done
  else
    VERSION="${VERSION#v}"
  fi
  [[ "${DISCOVERED_VERSION}" == "${VERSION}" ]] || fail "upgrade metadata does not match requested version"
  if [[ "${EXISTING_INSTALL}" == "true" ]]; then
    python3 "${TMP_DIR}/${UPGRADE_HELPER}" validate-metadata --metadata "${TMP_DIR}/${UPGRADE_METADATA}" \
      --current "${CURRENT_VERSION}" --target "${VERSION}" >/dev/null || { printf '{"audit_code":"rejected_before_change","reason":"unsupported_upgrade_path"}\n' >&2; exit 20; }
  fi
fi

prepare_downloaded_agent_binary "${TMP_DIR}/${BINARY}" || fail "target binary mode update failed"
if ! TARGET_VERSION="$(read_agent_version "${TMP_DIR}/${BINARY}")"; then
  fail "target binary version check failed"
fi
if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" == "true" && "${VERSION}" == "latest" ]]; then
  VERSION="${TARGET_VERSION}"
fi
[[ "${TARGET_VERSION}" == "${VERSION#v}" ]] || { printf '{"audit_code":"rejected_before_change","reason":"target_version_mismatch"}\n' >&2; exit 20; }

install -d -m 0755 "${INSTALL_DIR}" "${CONFIG_DIR}" /usr/local/libexec
install -d -m 0700 "${DATA_DIR}" "${UPGRADE_STATE_DIR}"
if [[ ! -f "${MACHINE_ID_FILE}" ]]; then
  if [[ -f "${IDENTITY_FILE}" && -r /etc/machine-id ]]; then
    tr -d '\n' </etc/machine-id >"${MACHINE_ID_FILE}"
  else
    [[ -r /proc/sys/kernel/random/uuid ]] || fail "kernel UUID generator is unavailable"
    tr -d '\n' </proc/sys/kernel/random/uuid >"${MACHINE_ID_FILE}"
  fi
  chmod 0600 "${MACHINE_ID_FILE}"
fi

CANDIDATE_ENV="${TMP_DIR}/agent.env"
CANDIDATE_UNIT="${TMP_DIR}/vps-agent.service"
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
  printf 'AGENT_OPERATION_POLICY=%s\n' "${AGENT_OPERATION_POLICY}"
  printf 'AGENT_OPERATION_KEY_ID=%s\n' "${OPERATION_KEY_ID}"
  printf 'AGENT_OPERATION_PUBLIC_KEY_BASE64=%s\n' "${OPERATION_PUBLIC_KEY}"
  printf 'AGENT_OPERATION_STATE_FILE=%s\n' "${DATA_DIR}/operations.json"
  printf 'AGENT_DEPLOY_POLICY=%s\n' "${AGENT_DEPLOY_POLICY}"
  printf 'AGENT_DEPLOY_ALLOWED_ROOTS=%s\n' "${DEPLOY_ALLOWED_ROOT}"
  if [[ ! -f "${IDENTITY_FILE}" ]]; then
    printf 'AGENT_REGISTRATION_TOKEN=%s\n' "${REGISTRATION_TOKEN}"
  fi
} >"${CANDIDATE_ENV}"
chmod 0600 "${CANDIDATE_ENV}"

{
cat <<'EOF'
[Unit]
Description=AI VPS Operations Agent
Wants=network-online.target
After=network-online.target
EOF
if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]]; then
cat <<'EOF'
Requires=vps-agent-upgrade-recovery.service
After=vps-agent-upgrade-recovery.service
EOF
fi
cat <<'EOF'

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
} >"${CANDIDATE_UNIT}"
chmod 0644 "${CANDIDATE_UNIT}"

if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]]; then
  install -m 0755 "${TMP_DIR}/${UPGRADE_HELPER}" "${INSTALLED_HELPER}"
  cat >"${RECOVERY_WRAPPER}" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
state=/var/lib/vps-agent/upgrades
if [[ -f "$state/transaction.json" ]]; then
  python3 /usr/local/libexec/vps-agent-upgrade.py recover-if-new-boot \
    --state-dir "$state" --boot-id "$(tr -d '\n' </proc/sys/kernel/random/boot_id)"
  systemctl daemon-reload
fi
EOF
  chmod 0755 "${RECOVERY_WRAPPER}"
  cat >"${RECOVERY_UNIT}" <<'EOF'
[Unit]
Description=Recover interrupted VPS Agent upgrade
Before=vps-agent.service

[Service]
Type=oneshot
ExecStart=/usr/local/libexec/vps-agent-upgrade-recover
EOF
  chmod 0644 "${RECOVERY_UNIT}"
fi

if [[ "${EXISTING_INSTALL}" == "true" && "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]]; then
  TRANSACTION_ID="$(tr -d '\n' </proc/sys/kernel/random/uuid)"
  BOOT_ID="$(tr -d '\n' </proc/sys/kernel/random/boot_id)"
  if ! python3 "${INSTALLED_HELPER}" prepare --state-dir "${UPGRADE_STATE_DIR}" \
    --candidate-binary "${TMP_DIR}/${BINARY}" --candidate-env "${CANDIDATE_ENV}" --candidate-unit "${CANDIDATE_UNIT}" \
    --binary "${INSTALL_DIR}/vps-agent" --env "${ENV_FILE}" --unit "${AGENT_UNIT}" \
    --current-version "${CURRENT_VERSION}" --target-version "${TARGET_VERSION}" \
    --boot-id "${BOOT_ID}" --transaction-id "${TRANSACTION_ID}"; then
    printf '{"audit_code":"rejected_before_change","reason":"transaction_prepare_failed"}\n' >&2
    exit 20
  fi
else
  install -m 0755 "${TMP_DIR}/${BINARY}" "${INSTALL_DIR}/vps-agent"
  install -m 0600 "${CANDIDATE_ENV}" "${ENV_FILE}"
  install -m 0644 "${CANDIDATE_UNIT}" "${AGENT_UNIT}"
fi

systemctl daemon-reload
if [[ "${EXISTING_INSTALL}" == "true" ]]; then
  if ! systemctl restart vps-agent.service; then
    if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]] && python3 "${INSTALLED_HELPER}" rollback --state-dir "${UPGRADE_STATE_DIR}"; then
      systemctl daemon-reload
      systemctl restart vps-agent.service || { printf '{"audit_code":"activation_failed_rollback_failed"}\n' >&2; exit 31; }
      printf '{"audit_code":"activation_failed_rollback_succeeded"}\n' >&2
      exit 30
    fi
    printf '{"audit_code":"activation_failed_rollback_failed"}\n' >&2
    exit 31
  fi
  stable=true
  for _ in {1..30}; do
    if ! systemctl is-active --quiet vps-agent.service; then stable=false; break; fi
    sleep 1
  done
  if [[ "${stable}" != "true" ]]; then
    if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]] && python3 "${INSTALLED_HELPER}" rollback --state-dir "${UPGRADE_STATE_DIR}"; then
      systemctl daemon-reload
      systemctl restart vps-agent.service || { printf '{"audit_code":"activation_failed_rollback_failed"}\n' >&2; exit 31; }
      printf '{"audit_code":"activation_failed_rollback_succeeded"}\n' >&2
      exit 30
    fi
    printf '{"audit_code":"activation_failed_rollback_failed"}\n' >&2
    exit 31
  fi
  ACTIVE_VERSION="$(read_agent_version "${INSTALL_DIR}/vps-agent")" || ACTIVE_VERSION=""
  if [[ "${ACTIVE_VERSION}" != "${TARGET_VERSION}" ]]; then
    if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]] && python3 "${INSTALLED_HELPER}" rollback --state-dir "${UPGRADE_STATE_DIR}"; then
      systemctl daemon-reload
      systemctl restart vps-agent.service || { printf '{"audit_code":"activation_failed_rollback_failed"}\n' >&2; exit 31; }
      printf '{"audit_code":"activation_failed_rollback_succeeded","reason":"active_version_mismatch"}\n' >&2
      exit 30
    fi
    printf '{"audit_code":"activation_failed_rollback_failed","reason":"active_version_mismatch"}\n' >&2
    exit 31
  fi
  if [[ "${ALLOW_LEGACY_CHECKSUM_ONLY}" != "true" ]]; then
    if ! python3 "${INSTALLED_HELPER}" commit --state-dir "${UPGRADE_STATE_DIR}" >/dev/null; then
      printf '{"audit_code":"upgrade_commit_failed_pending_recovery"}\n' >&2
      exit 32
    fi
  fi
else
  systemctl enable --now vps-agent.service
fi

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
    printf '{"audit_code":"agent_registration_failed_after_install"}\n' >&2
    exit 1
  fi
fi

REGISTRATION_TOKEN=""
INSTALLED_VERSION="$(read_agent_version "${INSTALL_DIR}/vps-agent")" || INSTALLED_VERSION="unknown"
printf '\nInstalled vps-agent %s\n' "${INSTALLED_VERSION}"
printf 'Service: systemctl status vps-agent --no-pager\n'
printf 'Logs:    journalctl -u vps-agent -f\n'
