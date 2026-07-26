#!/bin/sh
set -eu

MODE=${1:-}
BACKUP_PACKAGE=${2:-}
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-}
COMPOSE_FILE=${COMPOSE_FILE:-$REPO_ROOT/deploy/compose.production.yaml}
RESTORE_AUDIT_DIR=${RESTORE_AUDIT_DIR:-$REPO_ROOT/.recovery-audit}

dc() {
    docker compose --project-name "$COMPOSE_PROJECT_NAME" \
        --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

fail() {
    echo "$1" >&2
    exit 1
}

[ "$MODE" = inspect ] || [ "$MODE" = restore ] || \
    fail "usage: $0 {inspect|restore} ABSOLUTE_BACKUP_PACKAGE"
case "$BACKUP_PACKAGE" in /*) ;; *) fail "backup package path must be absolute" ;; esac
[ -d "$BACKUP_PACKAGE" ] && [ ! -L "$BACKUP_PACKAGE" ] || \
    fail "backup package must be a real directory, not a symlink"
[ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ] || fail "ENV_FILE must name the isolated target environment"
[ -f "$COMPOSE_FILE" ] || fail "required Compose file not found"
case "${COMPOSE_PROJECT_NAME:-}" in
    vps-agent-restore-*) ;;
    *) fail "COMPOSE_PROJECT_NAME must start with vps-agent-restore-" ;;
esac
[ "${RESTORE_ISOLATED_TARGET:-}" = yes ] || \
    fail "RESTORE_ISOLATED_TARGET=yes is required"

for name in postgres.dump manifest.json SHA256SUMS; do
    [ -f "$BACKUP_PACKAGE/$name" ] && [ ! -L "$BACKUP_PACKAGE/$name" ] || \
        fail "backup package has a missing or unsafe $name"
done
[ "$(find "$BACKUP_PACKAGE" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" = 3 ] || \
    fail "backup package must contain exactly three regular files"
[ "$(wc -l <"$BACKUP_PACKAGE/SHA256SUMS" | tr -d ' ')" = 2 ] || \
    fail "SHA256SUMS must contain exactly two entries"
[ "$(sed -n 's/^[0-9a-f]\{64\} [ *]postgres\.dump$/valid/p' "$BACKUP_PACKAGE/SHA256SUMS")" = valid ] || \
    fail "SHA256SUMS has an invalid postgres.dump entry"
[ "$(sed -n 's/^[0-9a-f]\{64\} [ *]manifest\.json$/valid/p' "$BACKUP_PACKAGE/SHA256SUMS")" = valid ] || \
    fail "SHA256SUMS has an invalid manifest.json entry"
(
    cd "$BACKUP_PACKAGE"
    sha256sum -c SHA256SUMS >/dev/null
)
dc exec -T postgres pg_restore --list <"$BACKUP_PACKAGE/postgres.dump" >/dev/null

manifest_instance=$(sed -n 's/^[[:space:]]*"instance_id":[[:space:]]*"\([^"]*\)".*/\1/p' "$BACKUP_PACKAGE/manifest.json")
manifest_size=$(sed -n 's/^[[:space:]]*"size_bytes":[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$BACKUP_PACKAGE/manifest.json")
actual_size=$(wc -c <"$BACKUP_PACKAGE/postgres.dump" | tr -d ' ')
[ -n "$manifest_instance" ] && [ -n "$manifest_size" ] || fail "manifest is missing required fields"
[ "$manifest_size" = "$actual_size" ] || fail "dump size does not match manifest"
dc run -T --interactive --rm --no-deps api python -m app.recovery validate-manifest \
    <"$BACKUP_PACKAGE/manifest.json"

if [ "$MODE" = inspect ]; then
    echo "backup package checksum, archive and compatibility checks passed"
    exit 0
fi

[ "${RESTORE_CONFIRM_INSTANCE_ID:-}" = "$manifest_instance" ] || \
    fail "RESTORE_CONFIRM_INSTANCE_ID must exactly match the backup instance id"
case "$RESTORE_AUDIT_DIR" in /*) ;; *) fail "RESTORE_AUDIT_DIR must be absolute" ;; esac
case "$RESTORE_AUDIT_DIR" in /|/var|/var/log|/tmp|/opt|/home|/root) fail "RESTORE_AUDIT_DIR is too broad" ;; esac
[ ! -L "$RESTORE_AUDIT_DIR" ] || fail "RESTORE_AUDIT_DIR must not be a symlink"
mkdir -p -- "$RESTORE_AUDIT_DIR"
chmod 700 "$RESTORE_AUDIT_DIR"
dc run -T --interactive --rm --no-deps api python -m app.recovery validate-target \
    <"$BACKUP_PACKAGE/manifest.json"
dc exec -T postgres sh -c \
    'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction --no-owner --no-privileges' \
    <"$BACKUP_PACKAGE/postgres.dump"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
summary_partial="$RESTORE_AUDIT_DIR/.restore-$timestamp.json.partial"
summary="$RESTORE_AUDIT_DIR/restore-$timestamp.json"
dc run -T --interactive --rm --no-deps api python -m app.recovery verify-restored \
    <"$BACKUP_PACKAGE/manifest.json" >"$summary_partial"
chmod 600 "$summary_partial"
mv -- "$summary_partial" "$summary"
printf '%s\n' "$summary"
