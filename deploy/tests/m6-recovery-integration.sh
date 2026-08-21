#!/bin/sh
set -eu

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "Python 3 is required" >&2
    exit 1
fi

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d)
COMPOSE_PROJECT_NAME="vps-agent-restore-m6test-$$"
ENV_FILE="$TEST_ROOT/recovery.env"
BACKUP_DIR="$TEST_ROOT/backups"
AUDIT_DIR="$TEST_ROOT/audit"
export COMPOSE_PROJECT_NAME ENV_FILE BACKUP_DIR RESTORE_AUDIT_DIR

case "$COMPOSE_PROJECT_NAME" in vps-agent-restore-m6test-*) ;; *) exit 1 ;; esac

dc() {
    docker compose --project-name "$COMPOSE_PROJECT_NAME" \
        --env-file "$ENV_FILE" -f "$REPO_ROOT/deploy/compose.production.yaml" "$@"
}

cleanup() {
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    case "$TEST_ROOT" in /tmp/*|/var/tmp/*) rm -rf -- "$TEST_ROOT" ;; esac
}
trap cleanup EXIT HUP INT TERM

cat >"$ENV_FILE" <<'EOF'
CONTROL_PLANE_DOMAIN=recovery.invalid
CONTROL_PLANE_INSTANCE_ID=m6-recovery-test
CONTROL_PLANE_VERSION=0.6.1-test
CONTROL_PLANE_COMMIT_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
CONTROL_PLANE_BUILD_TIME=2026-07-26T00:00:00Z
CADDY_ADMIN_USER=test
CADDY_ADMIN_PASSWORD_HASH=unused
CADDY_OPERATOR_USER=test-operator
CADDY_OPERATOR_PASSWORD_HASH=unused-operator
CADDY_APPROVER_USER=test-approver
CADDY_APPROVER_PASSWORD_HASH=unused-approver
POSTGRES_DB=vps_agent
POSTGRES_USER=vps_agent
POSTGRES_PASSWORD=m6_recovery_test
ADMIN_API_TOKEN=m6_recovery_admin
OPERATION_SIGNING_KEY_ID=production-sentinel-key
OPERATION_SIGNING_PRIVATE_KEY_BASE64=production-sentinel-private-key
PRINCIPAL_PROXY_TOKEN=production-sentinel-read-token
PRINCIPAL_WRITE_PROXY_TOKEN=production-sentinel-write-token
PRINCIPAL_ROLE_BINDINGS_JSON=[{"auth_source":"caddy_basic","auth_subject":"production-sentinel","principal_id":"local:4bf4ab08-4da6-44bb-8607-3c87f1946012","display_name":"Production Sentinel","roles":["operator"]}]
PRINCIPAL_VIEWER_IDS=production-sentinel-viewer
AGENT_OPERATION_KEY_ID=production-sentinel-agent-key
AGENT_OPERATION_PUBLIC_KEY_BASE64=production-sentinel-agent-public-key
EOF

RESTORE_SOURCE_INSTANCE_ID=m6-recovery-test
export RESTORE_SOURCE_INSTANCE_ID

dc build api
dc up -d --wait postgres
dc run -T --rm --no-deps api sh -c \
    'cd /app && exec alembic -c /app/alembic.ini upgrade head'
dc exec -T postgres psql -v ON_ERROR_STOP=1 -U vps_agent -d vps_agent <<'SQL'
INSERT INTO agents (
  id, organization_id, credential_hash, name, hostname, machine_id,
  os, arch, version, capabilities, created_at, updated_at
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'local',
  'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  'recovery-test', 'recovery-test', 'recovery-test', 'Linux', 'amd64',
  'test', '[]', now(), now()
);
SQL

package=$(sh "$REPO_ROOT/deploy/control-plane-backup.sh" integration)
test -f "$package/postgres.dump"
test -f "$package/manifest.json"
test -f "$package/SHA256SUMS"

DR_AGE_BINARY=${DR_AGE_BINARY:-/opt/vps-agent/tools/age/1.3.1/age}
test -x "$DR_AGE_BINARY"
AGE_KEYGEN=$(dirname "$DR_AGE_BINARY")/age-keygen
if [ ! -x "$AGE_KEYGEN" ] && [ -x "$AGE_KEYGEN.exe" ]; then
    AGE_KEYGEN="$AGE_KEYGEN.exe"
fi
test -x "$AGE_KEYGEN"
identity_a="$TEST_ROOT/identity-a.txt"
identity_b="$TEST_ROOT/identity-b.txt"
wrong_identity="$TEST_ROOT/identity-wrong.txt"
"$AGE_KEYGEN" -o "$identity_a" >/dev/null
"$AGE_KEYGEN" -o "$identity_b" >/dev/null
"$AGE_KEYGEN" -o "$wrong_identity" >/dev/null
chmod 600 "$identity_a" "$identity_b" "$wrong_identity"
recipient_a=$(sed -n 's/^# public key: //p' "$identity_a")
recipient_b=$(sed -n 's/^# public key: //p' "$identity_b")
printf '%s\n%s\n' "$recipient_a" "$recipient_b" >"$TEST_ROOT/recipients.txt"
chmod 644 "$TEST_ROOT/recipients.txt"
mkdir "$TEST_ROOT/encrypted" "$TEST_ROOT/dr-audit" "$TEST_ROOT/replica-a" "$TEST_ROOT/replica-b"
case "$(uname -s)" in
    MINGW*|MSYS*)
        python_path() { cygpath -w "$1"; }
        shell_path() { cygpath -u "$1"; }
        ;;
    *)
        python_path() { printf '%s\n' "$1"; }
        shell_path() { printf '%s\n' "$1"; }
        ;;
esac
DR_SCRIPT=$(python_path "$REPO_ROOT/scripts/disaster_recovery.py")
DR_POLICY=$(python_path "$TEST_ROOT/dr-policy.json")
"$PYTHON_BIN" - "$DR_POLICY" "$DR_AGE_BINARY" "$(python_path "$TEST_ROOT/recipients.txt")" \
    "$(python_path "$TEST_ROOT/encrypted")" "$(python_path "$BACKUP_DIR")" \
    "$(python_path "$REPO_ROOT/deploy/compose.production.yaml")" \
    "$(python_path "$ENV_FILE")" "$(python_path "$TEST_ROOT/dr-audit")" \
    "$(python_path "$TEST_ROOT/replica-a")" "$(python_path "$TEST_ROOT/replica-b")" <<'PY'
import json, sys
from pathlib import Path
policy, age, recipients, package_root, database_root, compose, env_file, audit, replica_a, replica_b = map(Path, sys.argv[1:])
value = {
    "format_version": "m6.1d-policy-v1",
    "instance_id": "m6-recovery-test",
    "age_binary": str(age.resolve()),
    "recipients_file": str(recipients.resolve()),
    "package_root": str(package_root.resolve()),
    "database_backup_root": str(database_root.resolve()),
    "audit_root": str(audit.resolve()),
    "control_plane_version": "0.6.1-test",
    "control_plane_commit_sha": "a" * 40,
    "alembic_revision": "0020_m6_named_approval",
    "postgres_major": 16,
    "files": {
        "config": [{"name": "compose.production.yaml", "path": str(compose.resolve())}],
        "secrets": [{"name": ".env.production", "path": str(env_file.resolve())}],
    },
    "replicas": [
        {"failure_domain": "ci-a", "root": str(replica_a.resolve())},
        {"failure_domain": "ci-b", "root": str(replica_b.resolve())},
    ],
}
policy.write_text(json.dumps(value), encoding="utf-8")
PY
encrypted_result=$("$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" create --kind database --database-package "$(python_path "$package")")
encrypted_package_python=$(printf '%s' "$encrypted_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
encrypted_package=$(shell_path "$encrypted_package_python")
"$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" replicate --package "$encrypted_package_python" >/dev/null
for identity in "$identity_a" "$identity_b"; do
    "$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" decrypt-verify --package "$encrypted_package_python" --identity "$(python_path "$identity")" >/dev/null
done
if "$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" decrypt-verify --package "$encrypted_package_python" --identity "$(python_path "$wrong_identity")"; then
    echo "wrong age identity was unexpectedly accepted" >&2
    exit 1
fi
secret_result=$("$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" create --kind secrets)
secret_package_python=$(printf '%s' "$secret_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
secret_package=$(shell_path "$secret_package_python")
"$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" replicate --package "$secret_package_python" >/dev/null
config_result=$("$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" create --kind config)
config_package_python=$(printf '%s' "$config_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
config_package=$(shell_path "$config_package_python")
"$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" replicate --package "$config_package_python" >/dev/null
mkdir "$TEST_ROOT/decrypted"
"$PYTHON_BIN" "$DR_SCRIPT" --policy "$DR_POLICY" decrypt-verify --package "$encrypted_package_python" --identity "$(python_path "$identity_a")" --output "$(python_path "$TEST_ROOT/decrypted")" >/dev/null
test -f "$TEST_ROOT/decrypted/database/postgres.dump"
test -f "$TEST_ROOT/replica-a/$(basename "$encrypted_package")/SHA256SUMS"
test -f "$TEST_ROOT/replica-b/$(basename "$encrypted_package")/SHA256SUMS"
test "$(find "$TEST_ROOT/dr-audit" -type f -name 'audit-*.json' | wc -l | tr -d ' ')" -ge 9

drill_env="$TEST_ROOT/drill.env"
sed \
    -e 's/^CONTROL_PLANE_INSTANCE_ID=.*/CONTROL_PLANE_INSTANCE_ID=m6-recovery-drill/' \
    -e 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=drill-only-postgres-password/' \
    -e 's/^ADMIN_API_TOKEN=.*/ADMIN_API_TOKEN=drill-only-admin-token-000000000000000000000000/' \
    "$ENV_FILE" >"$drill_env"
missing_caddy_env="$TEST_ROOT/drill-missing-caddy.env"
sed '/^CADDY_APPROVER_PASSWORD_HASH=/d' "$drill_env" >"$missing_caddy_env"
if DR_POLICY_FILE="$TEST_ROOT/dr-policy.json" \
    DR_TOOL="$REPO_ROOT/scripts/disaster_recovery.py" \
    DR_DRILL_LOCK_FILE=/tmp/vps-agent-disaster-recovery-drill.lock \
    COMPOSE_PROJECT_NAME="vps-agent-drill-missing-caddy-$$" \
    sh "$REPO_ROOT/deploy/control-plane-drill.sh" \
        "$encrypted_package" "$config_package" "$secret_package" "$identity_a" \
        "$missing_caddy_env" "$TEST_ROOT/drill-missing-caddy-audit"; then
    echo "drill env missing a required Caddy placeholder was unexpectedly accepted" >&2
    exit 1
fi
wrong_database_env="$TEST_ROOT/drill-wrong-database.env"
sed 's/^POSTGRES_DB=.*/POSTGRES_DB=wrong_drill_database/' \
    "$drill_env" >"$wrong_database_env"
if DR_POLICY_FILE="$TEST_ROOT/dr-policy.json" \
    DR_TOOL="$REPO_ROOT/scripts/disaster_recovery.py" \
    DR_DRILL_LOCK_FILE=/tmp/vps-agent-disaster-recovery-drill.lock \
    COMPOSE_PROJECT_NAME="vps-agent-drill-wrong-database-$$" \
    sh "$REPO_ROOT/deploy/control-plane-drill.sh" \
        "$encrypted_package" "$config_package" "$secret_package" "$identity_a" \
        "$wrong_database_env" "$TEST_ROOT/drill-wrong-database-audit"; then
    echo "drill env with an incompatible PostgreSQL database was unexpectedly accepted" >&2
    exit 1
fi
drill_config=$(docker compose --env-file "$drill_env" \
    -f "$REPO_ROOT/deploy/compose.production.yaml" \
    -f "$REPO_ROOT/deploy/compose.disaster-recovery.yaml" \
    --profile never config --format json)
printf '%s' "$drill_config" | "$PYTHON_BIN" -c '
import json, sys
services = json.load(sys.stdin)["services"]
for service, forbidden in {
    "caddy": {"CADDY_ADMIN_PASSWORD_HASH", "CADDY_OPERATOR_PASSWORD_HASH", "CADDY_APPROVER_PASSWORD_HASH", "PRINCIPAL_PROXY_TOKEN", "PRINCIPAL_WRITE_PROXY_TOKEN"},
    "web": {"PRINCIPAL_PROXY_TOKEN", "AGENT_OPERATION_KEY_ID", "AGENT_OPERATION_PUBLIC_KEY_BASE64"},
    "api": {"OPERATION_SIGNING_KEY_ID", "OPERATION_SIGNING_PRIVATE_KEY_BASE64", "PRINCIPAL_PROXY_TOKEN", "PRINCIPAL_WRITE_PROXY_TOKEN", "PRINCIPAL_ROLE_BINDINGS_JSON", "PRINCIPAL_VIEWER_IDS"},
}.items():
    assert forbidden.isdisjoint(services[service].get("environment", {})), (service, forbidden)
assert services["api"]["environment"]["ADMIN_API_TOKEN"].startswith("drill-only-")
'
DR_POLICY_FILE="$TEST_ROOT/dr-policy.json" \
DR_TOOL="$REPO_ROOT/scripts/disaster_recovery.py" \
DR_DRILL_LOCK_FILE=/tmp/vps-agent-disaster-recovery-drill.lock \
COMPOSE_PROJECT_NAME="vps-agent-drill-m6test-$$" \
sh "$REPO_ROOT/deploy/control-plane-drill.sh" \
    "$encrypted_package" "$config_package" "$secret_package" "$identity_a" \
    "$drill_env" "$TEST_ROOT/drill-audit" >/dev/null
test -f "$TEST_ROOT/drill-audit/"drill-*.json

dc down -v --remove-orphans
dc up -d --wait postgres

damaged="$TEST_ROOT/damaged-package"
cp -R "$package" "$damaged"
printf 'damage' >>"$damaged/postgres.dump"
if RESTORE_ISOLATED_TARGET=yes \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" inspect "$damaged"; then
    echo "damaged backup package was unexpectedly accepted" >&2
    exit 1
fi

case "$(uname -s)" in
    MINGW*|MSYS*) echo "symlink rejection case is deferred to the Linux CI runner" ;;
    *)
        ln -s "$package" "$TEST_ROOT/symlink-package"
        if RESTORE_ISOLATED_TARGET=yes \
            sh "$REPO_ROOT/deploy/control-plane-restore.sh" inspect \
            "$TEST_ROOT/symlink-package"; then
            echo "symlink backup package was unexpectedly accepted" >&2
            exit 1
        fi
        ;;
esac

incompatible="$TEST_ROOT/incompatible-package"
cp -R "$package" "$incompatible"
sed -i 's/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/' \
    "$incompatible/manifest.json"
(
    cd "$incompatible"
    sha256sum postgres.dump manifest.json >SHA256SUMS
)
if RESTORE_ISOLATED_TARGET=yes \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" inspect "$incompatible"; then
    echo "incompatible backup manifest was unexpectedly accepted" >&2
    exit 1
fi

wrong_revision="$TEST_ROOT/wrong-revision-package"
cp -R "$package" "$wrong_revision"
sed -i 's/0020_m6_named_approval/0019_m6_multichannel_notify/g' \
    "$wrong_revision/manifest.json"
(
    cd "$wrong_revision"
    sha256sum postgres.dump manifest.json >SHA256SUMS
)
if RESTORE_ISOLATED_TARGET=yes \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" inspect "$wrong_revision"; then
    echo "wrong Alembic revision was unexpectedly accepted" >&2
    exit 1
fi

wrong_major="$TEST_ROOT/wrong-major-package"
cp -R "$package" "$wrong_major"
sed -i 's/"postgres_major": 16/"postgres_major": 15/' \
    "$wrong_major/manifest.json"
(
    cd "$wrong_major"
    sha256sum postgres.dump manifest.json >SHA256SUMS
)
if RESTORE_ISOLATED_TARGET=yes \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" inspect "$wrong_major"; then
    echo "wrong PostgreSQL major was unexpectedly accepted" >&2
    exit 1
fi

if RESTORE_ISOLATED_TARGET=yes \
    RESTORE_SOURCE_INSTANCE_ID=wrong-source-instance \
    RESTORE_CONFIRM_INSTANCE_ID=m6-recovery-test \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$package"; then
    echo "manifest-derived source instance was unexpectedly accepted" >&2
    exit 1
fi

if RESTORE_ISOLATED_TARGET=yes \
    RESTORE_CONFIRM_INSTANCE_ID=wrong-instance \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$package"; then
    echo "wrong instance confirmation was unexpectedly accepted" >&2
    exit 1
fi

dc exec -T postgres psql -v ON_ERROR_STOP=1 -U vps_agent -d vps_agent \
    -c "CREATE TABLE restore_refusal_marker (id integer PRIMARY KEY)" >/dev/null
if RESTORE_ISOLATED_TARGET=yes \
    RESTORE_CONFIRM_INSTANCE_ID=m6-recovery-test \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$package"; then
    echo "non-empty restore target was unexpectedly accepted" >&2
    exit 1
fi
marker=$(dc exec -T postgres psql -At -U vps_agent -d vps_agent \
    -c "SELECT count(*) FROM pg_class WHERE relname = 'restore_refusal_marker'")
[ "$marker" = 1 ]
dc exec -T postgres psql -v ON_ERROR_STOP=1 -U vps_agent -d vps_agent \
    -c "DROP TABLE restore_refusal_marker" >/dev/null

RESTORE_ISOLATED_TARGET=yes \
RESTORE_CONFIRM_INSTANCE_ID=m6-recovery-test \
RESTORE_AUDIT_DIR="$AUDIT_DIR" \
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$TEST_ROOT/decrypted/database"

count=$(dc exec -T postgres psql -At -U vps_agent -d vps_agent \
    -c "SELECT count(*) FROM agents WHERE machine_id = 'recovery-test'")
[ "$count" = 1 ]
dc run -T --rm --no-deps api python -m app.schema check
test "$(find "$AUDIT_DIR" -type f -name 'restore-*.json' | wc -l | tr -d ' ')" = 1
echo "M6.1d PostgreSQL backup, age encryption, dual-fault-domain replica, decrypt and isolated restore integration passed"
