#!/bin/sh
set -eu

# Regression test for agent --version stream handling and the installer's
# read_agent_version detection. Covers the stderr/stdout compatibility fix:
# older agents (<= 0.6.3) print --version to stderr, newer agents print to
# stdout; the installer must recognize both and fail closed on anything else.

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
INSTALLER="$REPO_ROOT/scripts/install-agent.sh"
TEST_ROOT=$(mktemp -d /tmp/vps-agent-version-detection.XXXXXX)

cleanup() { rm -rf "$TEST_ROOT"; }
trap cleanup EXIT INT TERM

if [ ! -f "$INSTALLER" ]; then
    echo "install-agent.sh not found at $INSTALLER" >&2
    exit 1
fi

# run_read_version <binary> -> prints detected version, returns installer exit
run_read_version() {
    bash "$INSTALLER" __selftest_read_version__ "$1"
}

# --- 1. Real agent binary: version must go to stdout, stderr empty ---------
if command -v go >/dev/null 2>&1; then
    (
        cd "$REPO_ROOT/apps/agent"
        go build -o "$TEST_ROOT/real-agent" ./cmd/agent
    )
    stdout_file="$TEST_ROOT/real-stdout"
    stderr_file="$TEST_ROOT/real-stderr"
    "$TEST_ROOT/real-agent" --version >"$stdout_file" 2>"$stderr_file"
    if [ -s "$stderr_file" ]; then
        echo "real agent --version wrote to stderr: $(cat "$stderr_file")" >&2
        exit 1
    fi
    grep -Eq '^vps-agent [0-9]+\.[0-9]+\.[0-9]+$' "$stdout_file" || {
        echo "real agent --version stdout is not 'vps-agent X.Y.Z': $(cat "$stdout_file")" >&2
        exit 1
    }
    detected=$(run_read_version "$TEST_ROOT/real-agent")
    [ -n "$detected" ] || { echo "installer failed to read real agent version" >&2; exit 1; }
    echo "real agent version detected: $detected (stdout, stderr empty)"
else
    echo "go not available; skipping real agent --version build check" >&2
fi

# --- 2. Stub helpers --------------------------------------------------------
write_stub() {
    path=$1
    body=$2
    cat >"$path" <<EOF
#!/bin/sh
$body
EOF
    chmod 0755 "$path"
}

# --- 3. Old-style agent: version on stderr -> must be recognized -----------
write_stub "$TEST_ROOT/old-stderr" 'if [ "${1:-}" = --version ]; then echo "vps-agent 0.4.2" >&2; exit 0; fi'
v=$(run_read_version "$TEST_ROOT/old-stderr") || { echo "stderr version not recognized" >&2; exit 1; }
[ "$v" = "0.4.2" ] || { echo "stderr version mismatch: $v" >&2; exit 1; }

# --- 4. New-style agent: version on stdout -> must be recognized -----------
write_stub "$TEST_ROOT/new-stdout" 'if [ "${1:-}" = --version ]; then echo "vps-agent 0.6.4"; exit 0; fi'
v=$(run_read_version "$TEST_ROOT/new-stdout") || { echo "stdout version not recognized" >&2; exit 1; }
[ "$v" = "0.6.4" ] || { echo "stdout version mismatch: $v" >&2; exit 1; }

# --- 5. Fail-closed cases ---------------------------------------------------
expect_reject() {
    name=$1
    stub=$2
    if run_read_version "$stub" >/dev/null 2>&1; then
        echo "expected rejection but accepted: $name" >&2
        exit 1
    fi
}

write_stub "$TEST_ROOT/nonzero" 'exit 3'
expect_reject "non-zero exit" "$TEST_ROOT/nonzero"

write_stub "$TEST_ROOT/empty" 'exit 0'
expect_reject "empty output" "$TEST_ROOT/empty"

write_stub "$TEST_ROOT/multiline" 'if [ "${1:-}" = --version ]; then echo "vps-agent 0.6.4"; echo "extra line"; exit 0; fi'
expect_reject "multi-line output" "$TEST_ROOT/multiline"

write_stub "$TEST_ROOT/badformat" 'if [ "${1:-}" = --version ]; then echo "vps-agent not.a.version"; exit 0; fi'
expect_reject "malformed version" "$TEST_ROOT/badformat"

write_stub "$TEST_ROOT/prefix-junk" 'if [ "${1:-}" = --version ]; then echo "warning: something"; echo "vps-agent 0.6.4" >&2; exit 0; fi'
expect_reject "mixed warning plus version" "$TEST_ROOT/prefix-junk"

write_stub "$TEST_ROOT/trailing-space" 'if [ "${1:-}" = --version ]; then printf "vps-agent 0.6.4 \n"; exit 0; fi'
expect_reject "trailing space" "$TEST_ROOT/trailing-space"

echo "Agent version detection regression test passed: real stdout/stderr, old stderr, new stdout, fail-closed edge cases"
