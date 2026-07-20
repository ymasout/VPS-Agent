#!/bin/sh
set -eu

MODE=${1:-}
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-$REPO_ROOT/deploy/.env.production}
COMPOSE_FILE=${COMPOSE_FILE:-$REPO_ROOT/deploy/compose.production.yaml}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/vps-agent-console}
ADOPTION_REVISION=0006_m4_safe_operations

dc() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup="$BACKUP_DIR/postgres-$label-$timestamp.dump"
    dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' >"$backup"
    chmod 600 "$backup"
    printf '%s\n' "$backup"
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

require_file "$ENV_FILE"
require_file "$COMPOSE_FILE"

case "$MODE" in
    adopt) adopt_database ;;
    preflight) preflight ;;
    migrate) migrate ;;
    reload-caddy) reload_caddy ;;
    postflight) postflight ;;
    *)
        echo "usage: $0 {adopt|preflight|migrate|reload-caddy|postflight}" >&2
        exit 2
        ;;
esac
