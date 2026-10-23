#!/usr/bin/env bash
# Install a separate hourly, public-only snapshot refresh timer.
# Never expose the coordinator's port or database through this service.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]] || { echo "Use sudo from Ghost SSH user" >&2;exit 2; }
mode=status
if [[ "$#" -gt 0 ]];then mode="$1";fi
case "$mode" in status|install|disable) ;; *) echo "Usage: sudo bash hive_public_refresh_timer.sh install|status|disable" >&2;exit 2;; esac
OWNER="$(printenv SUDO_USER || true)"
[[ "$OWNER" =~ ^[a-z_][a-z0-9_-]*$ && "$OWNER" != root ]] || { echo "Expected normal Ghost sudo owner" >&2;exit 2; }
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
[[ -n "$HOME_DIR" && -d "$HOME_DIR" ]] || exit 2
SOURCE="$HOME_DIR/genesis-product-source"
RUN="$SOURCE/scripts/hive_public_preview.sh"
WEB_ROOT="$HOME_DIR/genesis-product/state/hive-public"
TIMER=/etc/systemd/system/ghost-hive-public-refresh.timer
SERVICE=/etc/systemd/system/ghost-hive-public-refresh.service
if [[ "$mode" == status ]];then
  systemctl is-active ghost-hive-public-refresh.timer || true
  systemctl list-timers --no-pager ghost-hive-public-refresh.timer || true
  exit 0
fi
if [[ "$mode" == disable ]];then
  systemctl disable --now ghost-hive-public-refresh.timer || true
  exit 0
fi
[[ -f "$RUN" && -d "$WEB_ROOT/www" ]] || { echo "Start isolated public preview first" >&2;exit 2; }
if [[ -e "$TIMER" || -e "$SERVICE" ]];then
 echo "Existing public refresh unit found; refusing replace" >&2;exit 2
fi
cat > "$SERVICE" <<UNIT
[Unit]
Description=GHOST Hive sanitized public snapshot refresh

[Service]
Type=oneshot
User=$OWNER
Group=$OWNER
WorkingDirectory=$SOURCE
ExecStart=/usr/bin/bash $RUN refresh
Nice=10
TimeoutStartSec=80
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$HOME_DIR/genesis-product/state/hive-public
PrivateTmp=true
UNIT
cat > "$TIMER" <<'UNIT'
[Unit]
Description=Hourly refresh of PUBLIC aggregate-only Hive snapshot

[Timer]
OnCalendar=hourly
RandomizedDelaySec=5m
Persistent=true
Unit=ghost-hive-public-refresh.service

[Install]
WantedBy=timers.target
UNIT
chmod 0644 "$TIMER" "$SERVICE"
systemctl daemon-reload
systemctl enable --now ghost-hive-public-refresh.timer
echo "HIVE PUBLIC REFRESH TIMER ENABLED (public-snapshot-only)."
