#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "m6 Agent systemd integration test must run as root" >&2
    exit 1
fi
if [ ! -d /run/systemd/system ]; then
    echo "a real running systemd instance is required" >&2
    exit 1
fi

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d /tmp/vps-agent-upgrade-systemd.XXXXXX)
UNIT_NAME=vps-agent-m6-upgrade-test.service
UNIT_PATH="/etc/systemd/system/$UNIT_NAME"
RECOVERY_UNIT_NAME=vps-agent-m6-upgrade-recovery-test.service
RECOVERY_UNIT_PATH="/etc/systemd/system/$RECOVERY_UNIT_NAME"

cleanup() {
    systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    systemctl stop "$RECOVERY_UNIT_NAME" >/dev/null 2>&1 || true
    rm -f "$UNIT_PATH" "$RECOVERY_UNIT_PATH"
    systemctl daemon-reload >/dev/null 2>&1 || true
    rm -rf "$TEST_ROOT"
}
trap cleanup EXIT INT TERM

(
    exec 8>/run/lock/vps-agent-install.lock
    flock -n 8
    : >"$TEST_ROOT/lock-ready"
    sleep 3
) &
lock_holder=$!
while [ ! -f "$TEST_ROOT/lock-ready" ]; do sleep 0.1; done
set +e
bash "$REPO_ROOT/scripts/install-agent.sh" --url https://invalid.example \
    >"$TEST_ROOT/locked.out" 2>&1
locked_status=$?
set -e
wait "$lock_holder"
test "$locked_status" -eq 21
grep -F '"audit_code":"upgrade_locked"' "$TEST_ROOT/locked.out" >/dev/null

mkdir -p "$TEST_ROOT/live" "$TEST_ROOT/candidate" "$TEST_ROOT/data"
printf '{"agent_id":"identity-must-not-change"}\n' >"$TEST_ROOT/data/identity.json"
printf '{"operation":"ledger-must-not-change"}\n' >"$TEST_ROOT/data/operations.json"
printf 'AGENT_OPERATION_POLICY=docker_restart\nAGENT_DEPLOY_POLICY=plan_only\n' >"$TEST_ROOT/live/env"
chmod 0600 "$TEST_ROOT/live/env"

# write_agent <path> <version> <mode> [stream]
# stream defaults to stdout (new-style agents); pass "stderr" to emulate the
# real <= 0.6.3 agents whose Go println() writes --version to stderr.
write_agent() {
    path=$1
    version=$2
    mode=$3
    stream=${4:-stdout}
    if [ "$stream" = stderr ]; then
        redirect=' >&2'
    else
        redirect=''
    fi
    cat >"$path" <<EOF
#!/bin/sh
if [ "\${1:-}" = --version ]; then
    echo "vps-agent $version"$redirect
    exit 0
fi
if [ "$mode" = fail ]; then
    exit 1
fi
exec sleep 300
EOF
    chmod 0755 "$path"
}

write_unit() {
    path=$1
    cat >"$path" <<EOF
[Unit]
Description=VPS Agent M6 upgrade integration test

[Service]
Type=simple
EnvironmentFile=$TEST_ROOT/live/env
ExecStart=$TEST_ROOT/live/binary
Restart=no
EOF
    chmod 0644 "$path"
}

write_agent "$TEST_ROOT/live/binary" 0.4.2 ok stderr
write_unit "$UNIT_PATH"
systemctl daemon-reload
systemctl start "$UNIT_NAME"
systemctl is-active --quiet "$UNIT_NAME"

write_agent "$TEST_ROOT/candidate/binary" 0.6.1 ok
cp "$TEST_ROOT/live/env" "$TEST_ROOT/candidate/env"
write_unit "$TEST_ROOT/candidate/unit"
python3 "$REPO_ROOT/scripts/agent_upgrade.py" prepare \
    --state-dir "$TEST_ROOT/state" \
    --candidate-binary "$TEST_ROOT/candidate/binary" \
    --candidate-env "$TEST_ROOT/candidate/env" \
    --candidate-unit "$TEST_ROOT/candidate/unit" \
    --binary "$TEST_ROOT/live/binary" --env "$TEST_ROOT/live/env" --unit "$UNIT_PATH" \
    --current-version 0.4.2 --target-version 0.6.1 \
    --boot-id 11111111-1111-4111-8111-111111111111 \
    --transaction-id 22222222-2222-4222-8222-222222222222 >/dev/null
systemctl daemon-reload
systemctl restart "$UNIT_NAME"
sleep 1
systemctl is-active --quiet "$UNIT_NAME"
test "$("$TEST_ROOT/live/binary" --version 2>&1)" = "vps-agent 0.6.1"
python3 "$REPO_ROOT/scripts/agent_upgrade.py" commit --state-dir "$TEST_ROOT/state" >/dev/null

write_agent "$TEST_ROOT/candidate/binary" 0.6.2 fail
cp "$TEST_ROOT/live/env" "$TEST_ROOT/candidate/env"
write_unit "$TEST_ROOT/candidate/unit"
python3 "$REPO_ROOT/scripts/agent_upgrade.py" prepare \
    --state-dir "$TEST_ROOT/state" \
    --candidate-binary "$TEST_ROOT/candidate/binary" \
    --candidate-env "$TEST_ROOT/candidate/env" \
    --candidate-unit "$TEST_ROOT/candidate/unit" \
    --binary "$TEST_ROOT/live/binary" --env "$TEST_ROOT/live/env" --unit "$UNIT_PATH" \
    --current-version 0.6.1 --target-version 0.6.2 \
    --boot-id 11111111-1111-4111-8111-111111111111 \
    --transaction-id 33333333-3333-4333-8333-333333333333 >/dev/null
systemctl daemon-reload
systemctl restart "$UNIT_NAME" >/dev/null 2>&1 || true
sleep 1
if systemctl is-active --quiet "$UNIT_NAME"; then
    echo "bad candidate unexpectedly remained active" >&2
    exit 1
fi
python3 "$REPO_ROOT/scripts/agent_upgrade.py" rollback --state-dir "$TEST_ROOT/state" >/dev/null
systemctl daemon-reload
systemctl restart "$UNIT_NAME"
systemctl is-active --quiet "$UNIT_NAME"
test "$("$TEST_ROOT/live/binary" --version 2>&1)" = "vps-agent 0.6.1"

grep -Fqx 'AGENT_OPERATION_POLICY=docker_restart' "$TEST_ROOT/live/env"
grep -Fqx 'AGENT_DEPLOY_POLICY=plan_only' "$TEST_ROOT/live/env"
test "$(cat "$TEST_ROOT/data/identity.json")" = '{"agent_id":"identity-must-not-change"}'
test "$(cat "$TEST_ROOT/data/operations.json")" = '{"operation":"ledger-must-not-change"}'

write_agent "$TEST_ROOT/candidate/binary" 0.6.2 fail
cp "$TEST_ROOT/live/env" "$TEST_ROOT/candidate/env"
write_unit "$TEST_ROOT/candidate/unit"
python3 "$REPO_ROOT/scripts/agent_upgrade.py" prepare \
    --state-dir "$TEST_ROOT/state" \
    --candidate-binary "$TEST_ROOT/candidate/binary" \
    --candidate-env "$TEST_ROOT/candidate/env" \
    --candidate-unit "$TEST_ROOT/candidate/unit" \
    --binary "$TEST_ROOT/live/binary" --env "$TEST_ROOT/live/env" --unit "$UNIT_PATH" \
    --current-version 0.6.1 --target-version 0.6.2 \
    --boot-id 11111111-1111-4111-8111-111111111111 \
    --transaction-id 55555555-5555-4555-8555-555555555555 >/dev/null
cat >"$RECOVERY_UNIT_PATH" <<EOF
[Unit]
Description=VPS Agent M6 cross-boot recovery integration test
Before=$UNIT_NAME

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $REPO_ROOT/scripts/agent_upgrade.py recover-if-new-boot --state-dir $TEST_ROOT/state --boot-id 66666666-6666-4666-8666-666666666666
EOF
systemctl daemon-reload
systemctl start "$RECOVERY_UNIT_NAME"
test ! -f "$TEST_ROOT/state/transaction.json"
test "$("$TEST_ROOT/live/binary" --version 2>&1)" = "vps-agent 0.6.1"
systemctl daemon-reload
systemctl restart "$UNIT_NAME"
systemctl is-active --quiet "$UNIT_NAME"

echo "Agent systemd upgrade integration passed: lock, success, activation rollback, cross-boot oneshot, identity and policy preservation"
