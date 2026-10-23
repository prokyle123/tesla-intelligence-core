#!/usr/bin/env bash
# Operator-controlled hourly Hive research-only timer. No upload unless consent.
set -Eeuo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run via sudo for systemd timer setup, never for consent." >&2
  exit 2
fi
mode="status"
if [[ "$#" -gt 0 ]]; then mode="$1"; fi
case "$mode" in install|status|disable) ;; *) echo "Usage: sudo bash hive_hourly_timer.sh install|status|disable" >&2;exit 2;; esac
owner="$(printenv SUDO_USER || true)"
if [[ ! "$owner" =~ ^[a-z_][a-z0-9_-]*$ || "$owner" == root ]]; then
  echo "Run via sudo from the GHOST service user's SSH session." >&2;exit 2
fi
home="$(getent passwd "$owner" | cut -d: -f6)"
if [[ -z "$home" || ! -d "$home" ]]; then echo "Service user home missing." >&2;exit 2;fi
app="$home/genesis-product/current"
state="$home/genesis-product/state/hive-client"
python="/opt/ghost-tesla-ai/venv/bin/python"
db="/var/lib/ghost-tesla-ai/ghost_ai.sqlite3"
timer=/etc/systemd/system/ghost-hive-hourly.timer
service=/etc/systemd/system/ghost-hive-hourly.service
if [[ "$mode" == "status" ]]; then
  systemctl is-enabled ghost-hive-hourly.timer || true
  systemctl is-active ghost-hive-hourly.timer || true
  systemctl list-timers --no-pager ghost-hive-hourly.timer || true
  echo "Transfer policy: consent OFF unless explicitly enabled in GHOST Hive."
  exit 0
fi
if [[ "$mode" == "disable" ]]; then
  systemctl disable --now ghost-hive-hourly.timer || true
  echo "Hourly research timer disabled. Existing local consent unchanged."
  exit 0
fi
[[ -f "$app/genesis/hive_hourly.py" ]] || { echo "Staged worker code missing." >&2;exit 2; }
[[ -f "$db" ]] || { echo "Read-only GHOST source missing." >&2;exit 2; }
[[ -x "$python" ]] || { echo "Python venv missing." >&2;exit 2; }
[[ -d "$state" ]] || { echo "Client state missing." >&2;exit 2; }
[[ "$(stat -c '%a' "$state")" == "700" ]] || { echo "Client state permissions must be 700." >&2;exit 2; }
if [[ -e "$timer" || -e "$service" ]]; then
  echo "Existing hourly units found; refusing to replace." >&2;exit 2
fi
umask 022
cat > "$service" <<UNIT
[Unit]
Description=GHOST Hive consent-gated monthly research sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$owner
Group=$owner
WorkingDirectory=$app
Environment=PYTHONPATH=$app
ExecStart=$python -m genesis.hive_hourly --state-dir $state --source-db $db
Nice=10
TimeoutStartSec=90
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$state
PrivateTmp=true
UNIT
cat > "$timer" <<'UNIT'
[Unit]
Description=Check for newly scored GHOST Hive research every hour

[Timer]
OnCalendar=hourly
RandomizedDelaySec=5m
Persistent=true
Unit=ghost-hive-hourly.service

[Install]
WantedBy=timers.target
UNIT
chmod 0644 "$timer" "$service"
systemctl daemon-reload
systemctl enable --now ghost-hive-hourly.timer
echo "HOURLY HIVE TIMER INSTALLED; consent remains unchanged."
echo "Only approved monthly aggregate summaries may transmit while OPTED_IN/hourly."
