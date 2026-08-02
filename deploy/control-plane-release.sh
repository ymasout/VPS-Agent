#!/bin/sh
set -eu

MODE=${1:-}
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-$REPO_ROOT/deploy/.env.production}
COMPOSE_FILE=${COMPOSE_FILE:-$REPO_ROOT/deploy/compose.production.yaml}
COMPOSE_OVERRIDE_FILE=${COMPOSE_OVERRIDE_FILE:-}
RELEASE_IMAGE_ENV_FILE=${RELEASE_IMAGE_ENV_FILE:-}
RELEASE_STAGED_DIR=${RELEASE_STAGED_DIR:-}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/vps-agent-console}
ADOPTION_REVISION=0006_m4_safe_operations

dc() {
    if [ -n "$COMPOSE_OVERRIDE_FILE" ] && [ -n "$RELEASE_IMAGE_ENV_FILE" ]; then
        docker compose --env-file "$ENV_FILE" --env-file "$RELEASE_IMAGE_ENV_FILE" \
            -f "$COMPOSE_FILE" -f "$COMPOSE_OVERRIDE_FILE" "$@"
    elif [ -n "$COMPOSE_OVERRIDE_FILE" ]; then
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$COMPOSE_OVERRIDE_FILE" "$@"
    else
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
}

require_file() {
    if [ ! -f "$1" ]; then
        echo "required file not found: $1" >&2
        exit 1
    fi
}

require_url() {
    if [ -z "${CONTROL_PLANE_URL:-}" ]; then
        echo "CONTROL_PLANE_URL is required for postflight checks" >&2
        exit 1
    fi
    CONTROL_PLANE_URL=${CONTROL_PLANE_URL%/}
}

backup_database() {
    label=$1
    ENV_FILE="$ENV_FILE" COMPOSE_FILE="$COMPOSE_FILE" BACKUP_DIR="$BACKUP_DIR" \
        sh "$REPO_ROOT/deploy/control-plane-backup.sh" "$label"
}

adopt_database() {
    heads=$(dc run --rm --no-deps api alembic -c /app/alembic.ini heads)
    case "$heads" in
        *"$ADOPTION_REVISION (head)"*) ;;
        *)
            echo "refusing one-time adoption: code head is no longer $ADOPTION_REVISION" >&2
            exit 1
            ;;
    esac
    backup=$(backup_database pre-adoption)
    dc run --rm --no-deps api python -m app.schema verify-adoption
    dc run --rm --no-deps api alembic -c /app/alembic.ini stamp head
    dc run --rm --no-deps api alembic -c /app/alembic.ini upgrade head
    dc run --rm --no-deps api python -m app.schema check
    echo "one-time Alembic adoption passed; backup=$backup"
}

preflight() {
    dc config --quiet
    dc config --format json | dc run --rm -T --no-deps api \
        python -m app.principal_deployment
    dc run --rm --no-deps caddy caddy validate --config /etc/caddy/cfg/Caddyfile

    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup=$(backup_database pre-migration)
    preview="$BACKUP_DIR/migration-$timestamp.sql"

    revisions=$(dc run --rm --no-deps api python -m app.schema revisions)
    current=$(printf '%s\n' "$revisions" | sed -n 's/^current=//p')
    if [ -z "$current" ] || [ "$current" = "unversioned" ]; then
        echo "database is not yet adopted by Alembic; run '$0 adopt' first" >&2
        exit 1
    fi
    dc run --rm --no-deps api alembic -c /app/alembic.ini upgrade "$current:head" --sql >"$preview"
    chmod 600 "$preview"
    echo "preflight passed; backup=$backup sql_preview=$preview"
    echo "the SQL file is a preview, not an execution dry run"
}

migrate() {
    dc run --rm --no-deps api alembic -c /app/alembic.ini upgrade head
}

reload_caddy() {
    if ! dc exec -T caddy caddy reload --config /etc/caddy/cfg/Caddyfile; then
        dc up -d --no-deps --force-recreate caddy
    fi
}

postflight() {
    require_url
    dc run --rm --no-deps api python -m app.schema check
    curl -fsS --connect-timeout 5 --max-time 20 "$CONTROL_PLANE_URL/healthz" >/dev/null
    curl -fsS --connect-timeout 5 --max-time 20 \
        "$CONTROL_PLANE_URL/api/v1/agents/operations/healthz" >/dev/null

    if [ -z "${CONTROL_PLANE_BASIC_AUTH:-}" ]; then
        echo "CONTROL_PLANE_BASIC_AUTH=user:password is required for the mapping-candidate check" >&2
        exit 1
    fi
    agents=$(curl -fsS --connect-timeout 5 --max-time 20 \
        -u "$CONTROL_PLANE_BASIC_AUTH" "$CONTROL_PLANE_URL/api/v1/agents")
    agent_id=$(printf '%s' "$agents" | dc run --rm -T --no-deps api python -c \
        'import json,sys; rows=json.load(sys.stdin); print(rows[0]["id"] if rows else "")')
    if [ -z "$agent_id" ]; then
        echo "postflight cannot check mapping candidates because no Agent is registered" >&2
        exit 1
    fi
    curl -fsS --connect-timeout 5 --max-time 20 -u "$CONTROL_PLANE_BASIC_AUTH" \
        "$CONTROL_PLANE_URL/api/v1/agents/$agent_id/service-mapping-candidates" >/dev/null
    echo "postflight passed: revision, schema, health, Agent operation route and mapping candidates"
}

require_release_mode() {
    if [ -z "$RELEASE_STAGED_DIR" ] || [ -z "$COMPOSE_OVERRIDE_FILE" ] || [ -z "$RELEASE_IMAGE_ENV_FILE" ]; then
        echo "release mode requires RELEASE_STAGED_DIR, COMPOSE_OVERRIDE_FILE and RELEASE_IMAGE_ENV_FILE" >&2
        exit 1
    fi
    for managed_path in \
        "$RELEASE_STAGED_DIR" \
        "$RELEASE_STAGED_DIR/.verified-release.json" \
        "$RELEASE_STAGED_DIR/release-manifest.json" \
        "$RELEASE_STAGED_DIR/deploy" \
        "$RELEASE_STAGED_DIR/deploy/release" \
        "$COMPOSE_FILE" "$COMPOSE_OVERRIDE_FILE" "$RELEASE_IMAGE_ENV_FILE"; do
        if [ -L "$managed_path" ]; then
            echo "verified staged release paths must not be symbolic links: $managed_path" >&2
            exit 1
        fi
    done
    require_file "$RELEASE_STAGED_DIR/.verified-release.json"
    require_file "$RELEASE_STAGED_DIR/release-manifest.json"
    require_file "$COMPOSE_OVERRIDE_FILE"
    require_file "$RELEASE_IMAGE_ENV_FILE"
    staged=$(realpath "$RELEASE_STAGED_DIR")
    expected_compose=$(realpath "$RELEASE_STAGED_DIR/deploy/compose.production.yaml")
    expected_override=$(realpath "$RELEASE_STAGED_DIR/deploy/release/compose.release.yaml")
    expected_images=$(realpath "$RELEASE_STAGED_DIR/deploy/release/images.env")
    if [ "$(realpath "$COMPOSE_FILE")" != "$expected_compose" ] || \
       [ "$(realpath "$COMPOSE_OVERRIDE_FILE")" != "$expected_override" ] || \
       [ "$(realpath "$RELEASE_IMAGE_ENV_FILE")" != "$expected_images" ]; then
        echo "release Compose and images must come from the verified staged directory: $staged" >&2
        exit 1
    fi
    python3 - "$RELEASE_STAGED_DIR/.verified-release.json" "$RELEASE_STAGED_DIR/release-manifest.json" \
        "$RELEASE_IMAGE_ENV_FILE" <<'PY'
import json, re, sys
from pathlib import Path
marker = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_marker = {"format_version", "archive_sha256", "version", "commit_sha", "schema_revision"}
if set(marker) != expected_marker or marker.get("format_version") != "vps-agent-staged-release-v1":
    raise SystemExit("verified release marker schema is invalid")
for key in ("version", "commit_sha", "schema_revision"):
    if marker.get(key) != manifest.get(key):
        raise SystemExit(f"verified release marker mismatch: {key}")
if not re.fullmatch(r"[0-9a-f]{64}", str(marker.get("archive_sha256", ""))):
    raise SystemExit("verified release archive hash is invalid")
images = {}
for line in Path(sys.argv[3]).read_text(encoding="ascii").splitlines():
    key, separator, value = line.partition("=")
    if not separator or key in images:
        raise SystemExit("release images.env is invalid")
    images[key] = value
if images != manifest.get("images"):
    raise SystemExit("release images.env does not match the staged manifest")
PY
    images=$(dc config --images)
    count=0
    for image in $images; do
        count=$((count + 1))
        if ! printf '%s\n' "$image" | grep -Eq '^[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'; then
            echo "release image is not a canonical digest reference: $image" >&2
            exit 1
        fi
    done
    if [ "$count" -ne 5 ]; then
        echo "release mode expected exactly five digest-pinned service images, got $count" >&2
        exit 1
    fi
}

release_pull() {
    require_release_mode
    dc pull api web caddy postgres redis
    echo "release images pulled by immutable digest"
}

release_check() {
    require_release_mode
    dc config --quiet
    echo "release Compose passed: five digest-pinned images and API/Web local builds removed"
}

release_up() {
    require_release_mode
    dc up -d --no-build
    echo "release services started with local builds disabled"
}

require_file "$ENV_FILE"
require_file "$COMPOSE_FILE"

case "$MODE" in
    adopt) adopt_database ;;
    preflight) preflight ;;
    migrate) migrate ;;
    reload-caddy) reload_caddy ;;
    postflight) postflight ;;
    release-check) release_check ;;
    release-pull) release_pull ;;
    release-up) release_up ;;
    *)
        echo "usage: $0 {adopt|preflight|migrate|reload-caddy|postflight|release-check|release-pull|release-up}" >&2
        exit 2
        ;;
esac
