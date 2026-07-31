#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
TMP_ROOT=$(mktemp -d)
REGISTRY_NAME="m6-release-registry-$$"
REGISTRY_PORT=5007
export COMPOSE_PROJECT_NAME="m6-release-integration-$$"
export ENV_FILE="$TMP_ROOT/production.env"
export COMPOSE_FILE="$REPO_ROOT/deploy/compose.production.yaml"
export COMPOSE_OVERRIDE_FILE="$REPO_ROOT/deploy/release/compose.release.yaml"
export RELEASE_IMAGE_ENV_FILE="$TMP_ROOT/images.env"
RELEASE_SCRIPT="$REPO_ROOT/deploy/control-plane-release.sh"
REGISTRY_IMAGE="registry@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
VERSION=0.6.1
COMMIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
BUILD_TIME=$(date -u -d "@$(git -C "$REPO_ROOT" show -s --format=%ct "$COMMIT_SHA")" +%Y-%m-%dT%H:%M:%SZ)

dc() {
    docker compose --env-file "$ENV_FILE" --env-file "$RELEASE_IMAGE_ENV_FILE" \
        -f "$COMPOSE_FILE" -f "$COMPOSE_OVERRIDE_FILE" "$@"
}

cleanup() {
    dc down --volumes --remove-orphans >/dev/null 2>&1 || true
    docker rm --force "$REGISTRY_NAME" >/dev/null 2>&1 || true
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT INT TERM

if [ -n "$(docker ps --quiet --filter "publish=${REGISTRY_PORT}")" ]; then
    echo "registry test port ${REGISTRY_PORT} is already in use" >&2
    exit 1
fi
docker run --detach --name "$REGISTRY_NAME" --publish "127.0.0.1:${REGISTRY_PORT}:5000" \
    "$REGISTRY_IMAGE" >/dev/null

API_REPOSITORY="localhost:${REGISTRY_PORT}/vps-agent-api"
WEB_REPOSITORY="localhost:${REGISTRY_PORT}/vps-agent-web"
docker build --file "$REPO_ROOT/apps/api/Dockerfile" \
    --build-arg "CONTROL_PLANE_VERSION=$VERSION" \
    --build-arg "CONTROL_PLANE_COMMIT_SHA=$COMMIT_SHA" \
    --build-arg "CONTROL_PLANE_BUILD_TIME=$BUILD_TIME" \
    --tag "$API_REPOSITORY:candidate" "$REPO_ROOT" >/dev/null
docker build --file "$REPO_ROOT/apps/web/Dockerfile" \
    --build-arg "CONTROL_PLANE_VERSION=$VERSION" \
    --build-arg "CONTROL_PLANE_COMMIT_SHA=$COMMIT_SHA" \
    --build-arg "CONTROL_PLANE_BUILD_TIME=$BUILD_TIME" \
    --tag "$WEB_REPOSITORY:candidate" "$REPO_ROOT" >/dev/null
docker push "$API_REPOSITORY:candidate" >/dev/null
docker push "$WEB_REPOSITORY:candidate" >/dev/null
API_IMAGE=$(docker image inspect --format '{{index .RepoDigests 0}}' "$API_REPOSITORY:candidate")
WEB_IMAGE=$(docker image inspect --format '{{index .RepoDigests 0}}' "$WEB_REPOSITORY:candidate")

cat >"$RELEASE_IMAGE_ENV_FILE" <<EOF
VPS_AGENT_API_IMAGE=$API_IMAGE
VPS_AGENT_WEB_IMAGE=$WEB_IMAGE
VPS_AGENT_CADDY_IMAGE=docker.io/library/caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648
VPS_AGENT_POSTGRES_IMAGE=docker.io/library/postgres@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777
VPS_AGENT_REDIS_IMAGE=docker.io/library/redis@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
EOF

CADDY_ADMIN_HASH=$(docker run --rm docker.io/library/caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648 \
    caddy hash-password --plaintext admin-password | sed 's/\$/$$/g')
CADDY_OPERATOR_HASH=$(docker run --rm docker.io/library/caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648 \
    caddy hash-password --plaintext operator-password | sed 's/\$/$$/g')
CADDY_APPROVER_HASH=$(docker run --rm docker.io/library/caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648 \
    caddy hash-password --plaintext approver-password | sed 's/\$/$$/g')

cat >"$ENV_FILE" <<EOF
CONTROL_PLANE_DOMAIN=localhost
CONTROL_PLANE_INSTANCE_ID=00000000-0000-4000-8000-000000000061
CONTROL_PLANE_VERSION=$VERSION
CONTROL_PLANE_COMMIT_SHA=$COMMIT_SHA
CONTROL_PLANE_BUILD_TIME=$BUILD_TIME
CADDY_ADMIN_USER=admin
CADDY_ADMIN_PASSWORD_HASH=$CADDY_ADMIN_HASH
CADDY_OPERATOR_USER=operator
CADDY_OPERATOR_PASSWORD_HASH=$CADDY_OPERATOR_HASH
CADDY_APPROVER_USER=approver
CADDY_APPROVER_PASSWORD_HASH=$CADDY_APPROVER_HASH
POSTGRES_DB=vps_agent
POSTGRES_USER=vps_agent
POSTGRES_PASSWORD=release-integration-postgres-password
ADMIN_API_TOKEN=release-integration-admin-token-000000000000000000000000
PRINCIPAL_CONTEXT_ENABLED=false
PRINCIPAL_READ_AUTHORIZATION_ENABLED=false
PRINCIPAL_PROXY_TOKEN=
PRINCIPAL_VIEWER_IDS=
PRINCIPAL_WRITE_CONTEXT_ENABLED=false
PRINCIPAL_WRITE_AUTHORIZATION_ENABLED=false
PRINCIPAL_BREAK_GLASS_ENABLED=false
PRINCIPAL_WRITE_PROXY_TOKEN=
PRINCIPAL_ROLE_BINDINGS_JSON=[]
EOF

sh "$RELEASE_SCRIPT" release-check
sh "$RELEASE_SCRIPT" release-pull
dc up --detach postgres redis
dc run --rm --no-deps api sh -eu -c \
    'test "$(pwd)" = /app; test -r /app/alembic.ini; test -d /app/migrations; alembic -c /app/alembic.ini upgrade head'
sh "$RELEASE_SCRIPT" release-up

for attempt in $(seq 1 60); do
    if dc exec -T api python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"; then
        break
    fi
    if [ "$attempt" -eq 60 ]; then
        dc ps
        dc logs api web
        exit 1
    fi
    sleep 1
done

dc run --rm --no-deps api python -m app.schema check
SYSTEM_INFO=$(dc exec -T api python -c \
    "import json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/api/v1/system-info',headers={'X-Admin-Token':'release-integration-admin-token-000000000000000000000000'}); print(urllib.request.urlopen(r).read().decode())")
printf '%s' "$SYSTEM_INFO" | dc exec -T api python -c \
    "import json,sys; p=json.load(sys.stdin); assert p['version']=='$VERSION'; assert p['commit_sha']=='$COMMIT_SHA'; assert p['schema_current'] is True"

for service in api web; do
    container_id=$(dc ps --quiet "$service")
    user=$(docker inspect "$container_id" --format '{{.Config.User}}')
    case "$service:$user" in
        api:10001:10001|web:node) ;;
        *) echo "unexpected runtime user: $service=$user" >&2; exit 1 ;;
    esac
done

echo "release-only image pull, migration, non-root runtime, health and build identity passed"
