#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -eq 0 ]]; then SUDO=""; else SUDO=sudo; fi
units=(ghost-tesla-ai-web.service ghost-tesla-ai-collector.service ghost-tesla-ai-train.timer ghost-tesla-ai-intelligence.timer ghost-tesla-ai-neural.timer ghost-tesla-ai-funnel-gateway.service)
for u in "${units[@]}"; do $SUDO systemctl disable --now "$u" 2>/dev/null || true; done
for f in /etc/systemd/system/ghost-tesla-ai-*; do [[ -e "$f" ]] && $SUDO rm -f "$f"; done
$SUDO systemctl daemon-reload
$SUDO rm -rf /opt/ghost-tesla-ai
$SUDO rm -f /usr/local/bin/ghost-ai
read -r -p "Delete learned data/models and config too? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then $SUDO rm -rf /var/lib/ghost-tesla-ai /etc/ghost-tesla-ai; else echo "Preserved /var/lib/ghost-tesla-ai and /etc/ghost-tesla-ai"; fi
echo "Tesla Intelligence Core removed."
