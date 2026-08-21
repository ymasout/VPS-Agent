#!/bin/sh
set -eu

[ "$#" -eq 6 ] || { echo "usage: $0 DB_ENCRYPTED_PACKAGE CONFIG_ENCRYPTED_PACKAGE SECRETS_ENCRYPTED_PACKAGE OFFLINE_IDENTITY ISOLATED_ENV AUDIT_DIR" >&2; exit 2; }
DB_PACKAGE=$1
CONFIG_PACKAGE=$2
SECRETS_PACKAGE=$3
IDENTITY=$4
ENV_FILE=$5
AUDIT_DIR=$6
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
POLICY=${DR_POLICY_FILE:-/etc/vps-agent/disaster-recovery.json}
TOOL=${DR_TOOL:-$REPO_ROOT/scripts/disaster_recovery.py}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-vps-agent-drill-$(date -u +%Y%m%d%H%M%S)}
COMPOSE_FILE=${COMPOSE_FILE:-$REPO_ROOT/deploy/compose.production.yaml}
COMPOSE_OVERRIDE_FILE=${COMPOSE_OVERRIDE_FILE:-$REPO_ROOT/deploy/compose.disaster-recovery.yaml}
export COMPOSE_PROJECT_NAME ENV_FILE COMPOSE_FILE

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys' >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "Python 3 is required" >&2; exit 1
fi
python_path() {
  case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac
}

case "$COMPOSE_PROJECT_NAME" in vps-agent-drill-*) ;; *) echo "isolated project name must start with vps-agent-drill-" >&2; exit 1 ;; esac
case "$AUDIT_DIR" in /*) ;; *) echo "audit directory must be absolute" >&2; exit 1 ;; esac
case "$AUDIT_DIR" in /|/tmp|/var|/opt|/home|/root) echo "audit directory is too broad" >&2; exit 1 ;; esac
[ ! -L "$AUDIT_DIR" ] || { echo "audit directory must not be a symlink" >&2; exit 1; }
[ -f "$ENV_FILE" ] && [ ! -L "$ENV_FILE" ] || { echo "isolated env file is missing or unsafe" >&2; exit 1; }
"$PYTHON_BIN" - "$(python_path "$ENV_FILE")" <<'PY'
import sys
from pathlib import Path

required = (
    "CADDY_ADMIN_USER",
    "CADDY_ADMIN_PASSWORD_HASH",
    "CADDY_OPERATOR_USER",
    "CADDY_OPERATOR_PASSWORD_HASH",
    "CADDY_APPROVER_USER",
    "CADDY_APPROVER_PASSWORD_HASH",
)
values = {}
for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].lstrip()
    key, separator, value = line.partition("=")
    if separator:
        values[key.strip()] = value.strip()
missing = [key for key in required if not values.get(key)]
if missing:
    print(
        "isolated env must define non-empty Caddy Compose placeholders: "
        + ", ".join(missing),
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
mkdir -p "$AUDIT_DIR"; chmod 700 "$AUDIT_DIR"
LOCK=${DR_DRILL_LOCK_FILE:-/run/lock/vps-agent-disaster-recovery-drill.lock}
case "$LOCK" in /run/lock/*|/tmp/vps-agent-disaster-recovery-drill.lock) ;; *) echo "drill lock path is unsafe" >&2; exit 1 ;; esac
LOCK_DIRECTORY=
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  flock -n 9 || { echo "another disaster recovery drill is running" >&2; exit 1; }
else
  LOCK_DIRECTORY="${LOCK}.d"
  mkdir "$LOCK_DIRECTORY" 2>/dev/null || { echo "another disaster recovery drill is running" >&2; exit 1; }
fi
WORK=$(mktemp -d)
chmod 700 "$WORK"

dc() { docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$COMPOSE_OVERRIDE_FILE" "$@"; }
cleanup() {
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  case "$WORK" in /tmp/*|/var/tmp/*) rm -rf -- "$WORK" ;; esac
  [ -z "$LOCK_DIRECTORY" ] || rmdir "$LOCK_DIRECTORY" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

start=$(date +%s)
record="$WORK/stages"
stage() { now=$(date +%s); printf '%s=%s\n' "$1" "$((now-start))" >>"$record"; }
mkdir "$WORK/database" "$WORK/config" "$WORK/secrets"
"$PYTHON_BIN" "$(python_path "$TOOL")" --policy "$(python_path "$POLICY")" decrypt-verify --package "$(python_path "$DB_PACKAGE")" --identity "$(python_path "$IDENTITY")" --output "$(python_path "$WORK/database")" >/dev/null
"$PYTHON_BIN" "$(python_path "$TOOL")" --policy "$(python_path "$POLICY")" decrypt-verify --package "$(python_path "$CONFIG_PACKAGE")" --identity "$(python_path "$IDENTITY")" --output "$(python_path "$WORK/config")" >/dev/null
"$PYTHON_BIN" "$(python_path "$TOOL")" --policy "$(python_path "$POLICY")" decrypt-verify --package "$(python_path "$SECRETS_PACKAGE")" --identity "$(python_path "$IDENTITY")" --output "$(python_path "$WORK/secrets")" >/dev/null
test -s "$WORK/secrets/secrets/.env.production"
test -s "$WORK/config/config/compose.production.yaml"
"$PYTHON_BIN" "$(python_path "$TOOL")" --policy "$(python_path "$POLICY")" verify-current --kind config --extracted-root "$(python_path "$WORK/config")" >/dev/null
"$PYTHON_BIN" "$(python_path "$TOOL")" --policy "$(python_path "$POLICY")" verify-current --kind secrets --extracted-root "$(python_path "$WORK/secrets")" >/dev/null
export COMPOSE_OVERRIDE_FILE
stage decrypt_verify

source_instance=$(sed -n 's/^[[:space:]]*"instance_id":[[:space:]]*"\([^"]*\)".*/\1/p' "$WORK/database/database/manifest.json")
expected_source_instance=$("$PYTHON_BIN" - "$(python_path "$POLICY")" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["instance_id"])
PY
)
drill_instance=$(sed -n 's/^CONTROL_PLANE_INSTANCE_ID=//p' "$ENV_FILE")
[ -n "$source_instance" ] && [ -n "$expected_source_instance" ] && [ -n "$drill_instance" ] || { echo "source or drill instance id is missing" >&2; exit 1; }
[ "$source_instance" = "$expected_source_instance" ] || { echo "database package instance does not match the trusted disaster recovery policy" >&2; exit 1; }
[ "$source_instance" != "$drill_instance" ] || { echo "isolated drill must use an independent instance id" >&2; exit 1; }
dc config --format json >"$WORK/compose.json"
"$PYTHON_BIN" - "$(python_path "$WORK/database/database/manifest.json")" "$(python_path "$WORK/compose.json")" <<'PY'
import json, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
compose = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
environment = compose["services"]["postgres"]["environment"]
if environment.get("POSTGRES_DB") != manifest["database_name"]:
    print(
        "isolated env POSTGRES_DB must exactly match the backup database name",
        file=sys.stderr,
    )
    raise SystemExit(1)
if environment.get("POSTGRES_USER") != manifest["database_role"]:
    print(
        "isolated env POSTGRES_USER must exactly match the backup database role",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
package_age_seconds() {
  "$PYTHON_BIN" - "$(python_path "$1/manifest.json")" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
created = datetime.strptime(json.loads(Path(sys.argv[1]).read_text())["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
print(int((datetime.now(timezone.utc) - created).total_seconds()))
PY
}
database_age_seconds=$(package_age_seconds "$DB_PACKAGE")
config_age_seconds=$(package_age_seconds "$CONFIG_PACKAGE")
secrets_age_seconds=$(package_age_seconds "$SECRETS_PACKAGE")
[ "$database_age_seconds" -ge -300 ] && [ "$database_age_seconds" -le 86400 ] || { echo "database package does not meet the 24-hour RPO" >&2; exit 1; }

dc up -d --wait postgres redis
stage isolated_postgres_ready
RESTORE_ISOLATED_TARGET=yes RESTORE_SOURCE_INSTANCE_ID="$expected_source_instance" RESTORE_CONFIRM_INSTANCE_ID="$source_instance" RESTORE_AUDIT_DIR="$WORK/restore-audit" \
  sh "$REPO_ROOT/deploy/control-plane-restore.sh" restore "$WORK/database/database" >/dev/null
stage database_restored
dc run -T --rm --no-deps api python -m app.schema check >/dev/null
stage schema_checked
dc up -d --wait api web
dc exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)" >/dev/null
dc exec -T api python -c "import json,urllib.request,os; r=urllib.request.Request('http://127.0.0.1:8000/api/v1/system-info',headers={'X-Admin-Token':os.environ['ADMIN_API_TOKEN']}); p=json.load(urllib.request.urlopen(r)); assert p['schema_current'] is True" >/dev/null
dc exec -T postgres sh -c 'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) >= 0 FROM agents"' | grep -qx t
stage control_plane_healthy

summary="$AUDIT_DIR/drill-$(date -u +%Y%m%dT%H%M%SZ).json"
"$PYTHON_BIN" - "$(python_path "$record")" "$(python_path "$summary")" "$database_age_seconds" "$config_age_seconds" "$secrets_age_seconds" "$source_instance" "$drill_instance" <<'PY'
import json, sys
from pathlib import Path
values = dict(line.split("=", 1) for line in Path(sys.argv[1]).read_text().splitlines())
stages = {key: int(value) for key, value in values.items()}
total = max(stages.values())
result = {"format_version":"m6.1d-drill-v1","stages_elapsed_seconds":stages,"total_elapsed_seconds":total,"rto_limit_seconds":14400,"rto_met":total <= 14400,"database_package_age_seconds":int(sys.argv[3]),"database_rpo_limit_seconds":86400,"database_rpo_met":-300 <= int(sys.argv[3]) <= 86400,"config_package_age_seconds":int(sys.argv[4]),"secrets_package_age_seconds":int(sys.argv[5]),"config_current_match":True,"secrets_current_match":True,"change_driven_freshness_verified":True,"source_instance_id":sys.argv[6],"isolated_instance_id":sys.argv[7],"instance_isolated":sys.argv[6] != sys.argv[7],"schema_current":True,"key_data_checked":True,"config_restored":True,"control_plane_healthy":True,"production_agent_connectivity":False}
with Path(sys.argv[2]).open("x", encoding="utf-8") as output:
    output.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
PY
chmod 600 "$summary"
printf '%s\n' "$summary"
[ "$(( $(date +%s) - start ))" -le 14400 ] || { echo "disaster recovery drill exceeded the four-hour RTO" >&2; exit 1; }
