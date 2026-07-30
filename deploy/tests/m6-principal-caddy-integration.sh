#!/bin/sh
set -eu

network="m6-principal-$$"
caddy_name="m6-principal-caddy-$$"
api_name="m6-principal-api-$$"
web_name="m6-principal-web-$$"
proxy_token="ci-principal-proxy-token-0000000000000000"

cleanup() {
    docker rm --force "$caddy_name" "$api_name" "$web_name" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create "$network" >/dev/null
docker run --detach --name "$api_name" --network "$network" --network-alias api \
    --volume "$PWD/deploy/tests/principal-header-echo.py:/echo.py:ro" \
    python:3.13-alpine python /echo.py 8000 >/dev/null
docker run --detach --name "$web_name" --network "$network" --network-alias web \
    --volume "$PWD/deploy/tests/principal-header-echo.py:/echo.py:ro" \
    python:3.13-alpine python /echo.py 3000 >/dev/null

password_hash="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext ci-password)"
docker run --detach --name "$caddy_name" --network "$network" \
    --publish 127.0.0.1:18080:8080 \
    --env CONTROL_PLANE_DOMAIN=:8080 \
    --env CADDY_ADMIN_USER=ci-user \
    --env CADDY_ADMIN_PASSWORD_HASH="$password_hash" \
    --env PRINCIPAL_PROXY_TOKEN="$proxy_token" \
    --volume "$PWD/deploy/caddy:/etc/caddy/cfg:ro" \
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
}

assert_trusted /api/v1/agents
assert_trusted /
assert_stripped /healthz
assert_stripped /api/v1/agents/register
assert_stripped /api/v1/github/webhooks
assert_stripped /agent-downloads/test

status="$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18080/)"
test "$status" = "401"
