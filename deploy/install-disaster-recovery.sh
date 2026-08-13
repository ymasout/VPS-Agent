#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
POLICY=${DR_POLICY_FILE:-/etc/vps-agent/disaster-recovery.json}

fail() { echo "$1" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "systemd disaster recovery installation must run as root"
[ -f "$POLICY" ] && [ ! -L "$POLICY" ] || fail "install the root-owned disaster recovery policy first"
[ "$(stat -c %u "$POLICY")" = 0 ] || fail "disaster recovery policy must be root-owned"
case "$(stat -c %a "$POLICY")" in
  400|440|444|600|640|644) ;;
  *) fail "disaster recovery policy must not be group/other writable" ;;
esac
for source in \
  "$REPO_ROOT/deploy/control-plane-backup.sh" \
  "$REPO_ROOT/deploy/control-plane-disaster-recovery.sh" \
  "$REPO_ROOT/deploy/systemd/run-database-backup" \
  "$REPO_ROOT/scripts/disaster_recovery.py" \
  "$REPO_ROOT/deploy/systemd/vps-agent-dr-database.service" \
  "$REPO_ROOT/deploy/systemd/vps-agent-dr-database.timer"; do
    [ -f "$source" ] && [ ! -L "$source" ] || fail "required systemd unit is missing or unsafe"
done
install -d -o root -g root -m 0755 /usr/local/libexec/vps-agent
install -o root -g root -m 0755 "$REPO_ROOT/deploy/control-plane-backup.sh" /usr/local/libexec/vps-agent/control-plane-backup.sh
install -o root -g root -m 0755 "$REPO_ROOT/deploy/control-plane-disaster-recovery.sh" /usr/local/libexec/vps-agent/control-plane-disaster-recovery.sh
install -o root -g root -m 0755 "$REPO_ROOT/deploy/systemd/run-database-backup" /usr/local/libexec/vps-agent/run-database-backup
install -o root -g root -m 0644 "$REPO_ROOT/scripts/disaster_recovery.py" /usr/local/libexec/vps-agent/disaster_recovery.py
install -o root -g root -m 0644 "$REPO_ROOT/deploy/systemd/vps-agent-dr-database.service" /etc/systemd/system/vps-agent-dr-database.service
install -o root -g root -m 0644 "$REPO_ROOT/deploy/systemd/vps-agent-dr-database.timer" /etc/systemd/system/vps-agent-dr-database.timer
systemd-analyze verify /etc/systemd/system/vps-agent-dr-database.service /etc/systemd/system/vps-agent-dr-database.timer
systemctl daemon-reload
systemctl enable --now vps-agent-dr-database.timer
systemctl is-enabled vps-agent-dr-database.timer >/dev/null
systemctl is-active vps-agent-dr-database.timer >/dev/null
printf '{"daily_timer_enabled":true,"success":true}\n'
