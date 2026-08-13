#!/bin/sh
set -eu

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "Python 3 is required" >&2
    exit 1
fi

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT INT TERM
STAGED="$TMP_ROOT/vps-agent-0.6.1"
mkdir -p "$STAGED/deploy/release"
cp "$REPO_ROOT/deploy/compose.production.yaml" "$STAGED/deploy/compose.production.yaml"
cp "$REPO_ROOT/deploy/release/compose.release.yaml" "$STAGED/deploy/release/compose.release.yaml"
grep '^VPS_AGENT_[A-Z_]*_IMAGE=' "$REPO_ROOT/deploy/release/.env.release.example" \
    >"$STAGED/deploy/release/images.env"
COMMIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
case "$(uname -s)" in MINGW*|MSYS*) STAGED_PY=$(cygpath -w "$STAGED") ;; *) STAGED_PY=$STAGED ;; esac
"$PYTHON_BIN" - "$STAGED_PY" "$COMMIT_SHA" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, commit = Path(sys.argv[1]), sys.argv[2]
images = dict(
    line.split("=", 1)
    for line in (root / "deploy/release/images.env").read_text(encoding="ascii").splitlines()
    if line and not line.startswith("#")
)
manifest = {
    "format_version": "m6.4d-release-v1",
    "version": "0.6.1",
    "tag": "v0.6.1",
    "commit_sha": commit,
    "schema_revision": "0020_m6_named_approval",
    "images": images,
    "created_at": "2026-08-01T00:00:00Z",
}
(root / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
marker = {
    "format_version": "vps-agent-staged-release-v1",
    "archive_sha256": hashlib.sha256(b"policy-fixture").hexdigest(),
    "version": "0.6.1",
    "commit_sha": commit,
    "schema_revision": "0020_m6_named_approval",
}
(root / ".verified-release.json").write_text(json.dumps(marker), encoding="utf-8")
PY

ENV_FILE="$REPO_ROOT/deploy/.env.production.example" \
COMPOSE_FILE="$STAGED/deploy/compose.production.yaml" \
COMPOSE_OVERRIDE_FILE="$STAGED/deploy/release/compose.release.yaml" \
RELEASE_IMAGE_ENV_FILE="$STAGED/deploy/release/images.env" \
RELEASE_STAGED_DIR="$STAGED" \
sh "$REPO_ROOT/deploy/control-plane-release.sh" release-check
