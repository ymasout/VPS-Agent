#!/bin/sh
set -eu

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
EOF

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
    sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$package"

count=$(dc exec -T postgres psql -At -U vps_agent -d vps_agent \
    -c "SELECT count(*) FROM agents WHERE machine_id = 'recovery-test'")
[ "$count" = 1 ]
dc run -T --rm --no-deps api python -m app.schema check
test "$(find "$AUDIT_DIR" -type f -name 'restore-*.json' | wc -l | tr -d ' ')" = 1
echo "M6.1 backup and isolated restore integration passed"
