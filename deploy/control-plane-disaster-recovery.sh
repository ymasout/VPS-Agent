#!/bin/sh
set -eu

ACTION=${1:-}
POLICY=${DR_POLICY_FILE:-/etc/vps-agent/disaster-recovery.json}
TOOL=${DR_TOOL:-/usr/local/libexec/vps-agent/disaster_recovery.py}
LOCK=${DR_LOCK_FILE:-/run/lock/vps-agent-disaster-recovery.lock}

fail() { echo "$1" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "disaster recovery commands must run as root"
case "$LOCK" in /run/lock/*) ;; *) fail "DR_LOCK_FILE must remain under /run/lock" ;; esac
command -v flock >/dev/null 2>&1 || fail "flock is required"
exec 9>"$LOCK"
flock -n 9 || fail "another disaster recovery task is running"
[ -f "$POLICY" ] && [ ! -L "$POLICY" ] || fail "disaster recovery policy is missing or unsafe"
[ -f "$TOOL" ] && [ ! -L "$TOOL" ] || fail "disaster recovery tool is missing or unsafe"
for root_file in "$POLICY" "$TOOL"; do
  [ "$(stat -c %u "$root_file")" = 0 ] || fail "disaster recovery policy and tool must be root-owned"
  case "$(stat -c %a "$root_file")" in
    ?[2367]?|??[2367]) fail "disaster recovery policy and tool must not be group/other writable" ;;
  esac
done

case "$ACTION" in
  database)
    [ "$#" -eq 2 ] || fail "usage: $0 database ABSOLUTE_DATABASE_PACKAGE"
    result=$(python3 "$TOOL" --policy "$POLICY" create --kind database --database-package "$2")
    package=$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')
    python3 "$TOOL" --policy "$POLICY" replicate --package "$package"
    ;;
  config|secrets)
    [ "$#" -eq 1 ] || fail "usage: $0 {config|secrets}"
    result=$(python3 "$TOOL" --policy "$POLICY" create --kind "$ACTION")
    package=$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')
    python3 "$TOOL" --policy "$POLICY" replicate --package "$package"
    ;;
  monthly-check)
    [ "$#" -eq 3 ] || fail "usage: $0 monthly-check ABSOLUTE_PACKAGE ABSOLUTE_OFFLINE_IDENTITY"
    python3 "$TOOL" --policy "$POLICY" decrypt-verify --package "$2" --identity "$3"
    ;;
  *) fail "usage: $0 {database ABSOLUTE_DATABASE_PACKAGE|config|secrets|monthly-check ABSOLUTE_PACKAGE ABSOLUTE_OFFLINE_IDENTITY}" ;;
esac
