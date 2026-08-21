#!/bin/sh
set -eu

repo_root=$PWD
case "$(uname -s)" in
    MINGW*|MSYS*)
        repo_root=$(cygpath -m "$PWD")
        export MSYS_NO_PATHCONV=1
        ;;
esac

network="m6-principal-$$"
caddy_name="m6-principal-caddy-$$"
api_name="m6-principal-api-$$"
web_name="m6-principal-web-$$"
proxy_token="ci-principal-proxy-token-0000000000000000"
write_token="ci-principal-write-token-000000000000000"

cleanup() {
    docker rm --force "$caddy_name" "$api_name" "$web_name" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create "$network" >/dev/null
docker run --detach --name "$api_name" --network "$network" --network-alias api \
    --volume "$repo_root/deploy/tests/principal-header-echo.py:/echo.py:ro" \
    python:3.13-alpine python /echo.py 8000 >/dev/null
docker run --detach --name "$web_name" --network "$network" --network-alias web \
    --volume "$repo_root/deploy/tests/principal-header-echo.py:/echo.py:ro" \
    python:3.13-alpine python /echo.py 3000 >/dev/null

password_hash="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext ci-password)"
operator_hash="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext operator-password)"
approver_hash="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext approver-password)"
docker run --detach --name "$caddy_name" --network "$network" \
    --publish 127.0.0.1:18080:8080 \
    --env CONTROL_PLANE_DOMAIN=:8080 \
    --env CADDY_ADMIN_USER=ci-user \
    --env CADDY_ADMIN_PASSWORD_HASH="$password_hash" \
    --env CADDY_OPERATOR_USER=ci-operator \
    --env CADDY_OPERATOR_PASSWORD_HASH="$operator_hash" \
    --env CADDY_APPROVER_USER=ci-approver \
    --env CADDY_APPROVER_PASSWORD_HASH="$approver_hash" \
    --env PRINCIPAL_PROXY_TOKEN="$proxy_token" \
    --env PRINCIPAL_WRITE_PROXY_TOKEN="$write_token" \
    --volume "$repo_root/deploy/caddy:/etc/caddy/cfg:ro" \
    caddy:2-alpine caddy run --config /etc/caddy/cfg/Caddyfile --adapter caddyfile >/dev/null

for _attempt in $(seq 1 30); do
    if curl --fail --silent http://127.0.0.1:18080/healthz >/dev/null; then
        break
    fi
    sleep 1
done

assert_trusted() {
    response="$(curl --fail --silent --user ci-user:ci-password \
        --header 'X-VPS-Agent-Principal-Id: forged' \
        --header 'X-VPS-Agent-Principal-Source: forged' \
        --header 'X-VPS-Agent-Principal-Proxy-Token: forged' \
        "http://127.0.0.1:18080$1")"
    printf '%s' "$response" | grep --fixed-strings '"id": "ci-user"' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"source": "caddy_basic"' >/dev/null
    printf '%s' "$response" | grep --fixed-strings "\"token\": \"$proxy_token\"" >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"write_token": null' >/dev/null
}

assert_write_trusted() {
    user="$1"
    password="$2"
    path="$3"
    response="$(curl --fail --silent --request POST --user "$user:$password" \
        --header 'Origin: https://ops.example.test' \
        --header 'Sec-Fetch-Site: same-origin' \
        --header 'Content-Type: application/json' \
        --header 'X-VPS-Agent-Principal-Id: forged' \
        --header 'X-VPS-Agent-Principal-Source: forged' \
        --header 'X-VPS-Agent-Principal-Proxy-Token: forged' \
        --header 'X-VPS-Agent-Principal-Write-Token: forged' \
        "http://127.0.0.1:18080$path")"
    printf '%s' "$response" | grep --fixed-strings "\"id\": \"$user\"" >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"source": "caddy_basic"' >/dev/null
    printf '%s' "$response" | grep --fixed-strings "\"token\": \"$proxy_token\"" >/dev/null
    printf '%s' "$response" | grep --fixed-strings "\"write_token\": \"$write_token\"" >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"origin": "https://ops.example.test"' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"sec_fetch_site": "same-origin"' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"content_type": "application/json"' >/dev/null
}

assert_write_stripped() {
    method="$1"
    path="$2"
    response="$(curl --fail --silent --request "$method" --user ci-operator:operator-password \
        --header 'X-VPS-Agent-Principal-Write-Token: forged' \
        "http://127.0.0.1:18080$path")"
    printf '%s' "$response" | grep --fixed-strings '"write_token": null' >/dev/null
}

assert_stripped() {
    response="$(curl --fail --silent \
        --header 'X-VPS-Agent-Principal-Id: forged' \
        --header 'X-VPS-Agent-Principal-Source: forged' \
        --header 'X-VPS-Agent-Principal-Proxy-Token: forged' \
        "http://127.0.0.1:18080$1")"
    printf '%s' "$response" | grep --fixed-strings '"id": null' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"source": null' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"token": null' >/dev/null
    printf '%s' "$response" | grep --fixed-strings '"write_token": null' >/dev/null
}

assert_trusted /api/v1/agents
assert_trusted /
assert_write_trusted ci-operator operator-password /api/v1/operations
assert_write_trusted ci-approver approver-password /api/v1/operations/op-1/confirm
assert_write_trusted ci-operator operator-password /api/v1/deployment-plans
assert_write_trusted ci-operator operator-password /api/v1/deployment-operations
assert_write_trusted ci-operator operator-password /api/v1/deployment-operations/op-1/rollback
assert_write_trusted ci-operator operator-password /api/v1/events/event-1/conversation/turns/turn-1/restart-plan
assert_write_trusted ci-operator operator-password /api/v1/events/event-1/conversation/turns/turn-1/rollback-plan
oversized_status="$(
    dd if=/dev/zero bs=1024 count=5 2>/dev/null |
        curl --silent --output /dev/null --write-out '%{http_code}' \
            --request POST --user ci-approver:approver-password \
            --header 'Content-Type: application/json' \
            --data-binary @- \
            http://127.0.0.1:18080/api/v1/operations/op-1/confirm
)"
test "$oversized_status" = "413"
assert_write_stripped GET /api/v1/operations
assert_write_stripped POST /api/v1/operations/op-1/cancel
assert_stripped /healthz
assert_stripped /api/v1/agents/register
assert_stripped /api/v1/github/webhooks
assert_stripped /agent-downloads/test

status="$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18080/)"
test "$status" = "401"
