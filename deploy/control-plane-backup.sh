#!/bin/sh
set -eu

LABEL=${1:-manual}
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-$REPO_ROOT/deploy/.env.production}
COMPOSE_FILE=${COMPOSE_FILE:-$REPO_ROOT/deploy/compose.production.yaml}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/vps-agent-console}
SNAPSHOT_PID=

dc() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

fail() {
    echo "$1" >&2
    exit 1
}

cleanup() {
    if [ -n "$SNAPSHOT_PID" ]; then
        kill "$SNAPSHOT_PID" 2>/dev/null || true
        wait "$SNAPSHOT_PID" 2>/dev/null || true
    fi
    if [ -n "${WORK_DIR:-}" ] && [ -d "$WORK_DIR" ]; then
        case "$WORK_DIR" in
            "$BACKUP_DIR"/.backup-*) rm -rf -- "$WORK_DIR" ;;
        esac
    fi
}
trap cleanup EXIT HUP INT TERM

case "$LABEL" in [a-z0-9]*) ;; *) fail "backup label must start with a lowercase letter or digit" ;; esac
case "$LABEL" in *[!a-z0-9._-]*) fail "backup label contains unsupported characters" ;; esac
[ "${#LABEL}" -le 32 ] || fail "backup label must be at most 32 characters"
case "$BACKUP_DIR" in /*) ;; *) fail "BACKUP_DIR must be absolute" ;; esac
case "$BACKUP_DIR" in /|/var|/var/backups|/tmp|/opt|/home|/root) fail "BACKUP_DIR is too broad" ;; esac
[ ! -L "$BACKUP_DIR" ] || fail "BACKUP_DIR must not be a symlink"
[ -f "$ENV_FILE" ] || fail "required environment file not found"
[ -f "$COMPOSE_FILE" ] || fail "required Compose file not found"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

mkdir -p -- "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
WORK_DIR=$(mktemp -d "$BACKUP_DIR/.backup-$timestamp-XXXXXX")
chmod 700 "$WORK_DIR"
snapshot_json="$WORK_DIR/snapshot.json"
dump_partial="$WORK_DIR/postgres.dump.partial"

dc run -T --rm --no-deps api python -m app.recovery export-snapshot \
    >"$snapshot_json" &
SNAPSHOT_PID=$!
attempt=0
while [ ! -s "$snapshot_json" ] && kill -0 "$SNAPSHOT_PID" 2>/dev/null; do
    attempt=$((attempt + 1))
    [ "$attempt" -le 200 ] || fail "timed out while exporting PostgreSQL snapshot"
    sleep 0.1
done
[ -s "$snapshot_json" ] || fail "snapshot exporter stopped before producing metadata"
snapshot_id=$(sed -n 's/.*"snapshot_id":"\([^"]*\)".*/\1/p' "$snapshot_json")
release_channel=$(sed -n 's/.*"release_channel":"\([^"]*\)".*/\1/p' "$snapshot_json")
[ -n "$snapshot_id" ] && [ -n "$release_channel" ] || \
    fail "snapshot exporter returned invalid metadata"

dc exec -T postgres sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --snapshot="$1"' \
    sh "$snapshot_id" >"$dump_partial"
dc run -T --rm --no-deps api python -m app.recovery release-snapshot "$release_channel"
wait "$SNAPSHOT_PID"
SNAPSHOT_PID=

dc exec -T postgres pg_restore --list <"$dump_partial" >/dev/null
mv -- "$dump_partial" "$WORK_DIR/postgres.dump"
chmod 600 "$WORK_DIR/postgres.dump"
dump_sha256=$(sha256sum "$WORK_DIR/postgres.dump" | awk '{print $1}')
dump_size=$(wc -c <"$WORK_DIR/postgres.dump" | tr -d ' ')
dc run -T --interactive --rm --no-deps api python -m app.recovery finalize-manifest \
    --label "$LABEL" --dump-sha256 "$dump_sha256" --dump-size "$dump_size" \
    <"$snapshot_json" >"$WORK_DIR/manifest.json"
rm -f -- "$snapshot_json"
chmod 600 "$WORK_DIR/manifest.json"
(
    cd "$WORK_DIR"
    sha256sum postgres.dump manifest.json >SHA256SUMS
    chmod 600 SHA256SUMS
    sha256sum -c SHA256SUMS >/dev/null
)

FINAL_DIR="$BACKUP_DIR/control-plane-$LABEL-$timestamp"
[ ! -e "$FINAL_DIR" ] || fail "backup destination already exists"
mv -- "$WORK_DIR" "$FINAL_DIR"
WORK_DIR=
trap - EXIT HUP INT TERM
printf '%s\n' "$FINAL_DIR"
