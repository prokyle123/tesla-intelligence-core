#!/usr/bin/env bash
# GHOST Hive v1 screenshot-style UI + isolated public localhost preview.
# This script NEVER modifies GHOST Home, telemetry, models, consent or client timers.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal Ghost SSH user." >&2;exit 2; }
MODE=install
if [[ "$#" -gt 0 ]];then MODE="$1";fi
case "$MODE" in check|install) ;; *) echo "Usage: bash hive_v1_ui_deploy.sh check|install" >&2;exit 2;; esac
SRC="$(cd "$(dirname "$0")/.." && pwd -P)"
LIVE=/opt/ghost-tesla-ai
PY="$LIVE/venv/bin/python"
PATCH="$SRC/scripts/ghost_hive_update.py"
BACKUP_PARENT="$HOME/ghost-hive-ui-backups"
VERIFY="$HOME/hive-v1-install-test.log"
test -x "$PY" || { echo "STOP: expected GHOST Python not found" >&2;exit 2; }
test -f "$LIVE/web/templates/index.html" || { echo "STOP: customized live Home missing" >&2;exit 2; }
test -f "$LIVE/ghost_tesla_ai/server.py" || { echo "STOP: Classic web server missing" >&2;exit 2; }
test -f "$SRC/docs/hive/index.html" || { echo "STOP: Public site source missing" >&2;exit 2; }
before_home="$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)"
before_server="$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)"
test_dir="$(mktemp -d /tmp/hive-ui-check.XXXXXXXX)"
trap 'rm -rf "$test_dir"' EXIT
echo "[1/5] Verifying reviewed frontend and offline tests..."
cd "$SRC"
if ! "$PY" -m unittest discover -s tests -p 'test_genesis_hive*.py' -q > "$VERIFY" 2>&1;then
  tail -40 "$VERIFY"
  exit 1
fi
echo "HIVE REGRESSION TESTS PASS"
echo "[2/5] Checking existing Hive-only files (NO Home changes)..."
mkdir -p "$BACKUP_PARENT";chmod 700 "$BACKUP_PARENT"
# Patcher check refuses unknown live source modifications, no matching prefix.
backup="$BACKUP_PARENT/preview-v1"
if [[ -e "$backup" ]];then
  backup="$BACKUP_PARENT/preview-$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
python3 "$PATCH" --live "$LIVE" --backup "$backup" --check
if [[ "$MODE" == check ]];then
  echo "PRECHECK PASS. Live services unchanged."
  exit 0
fi
echo "[3/5] Applying guarded Hive-only update..."
sudo -v
sudo python3 "$PATCH" --live "$LIVE" --backup "$backup" --apply
rollback(){
  echo "Web verification failed; attempting verified Hive-only rollback." >&2
  if sudo python3 "$PATCH" --live "$LIVE" --backup "$backup" --rollback;then
    sudo systemctl restart ghost-tesla-ai-web.service || true
    echo "Restored previous Hive UI. Existing Home intact." >&2
  else
    echo "Rollback requires manual inspection of backup: $backup" >&2
  fi
}
if ! sudo systemctl restart ghost-tesla-ai-web.service;then rollback;exit 1;fi
echo "[4/5] Validating real GHOST route and preserved Home..."
if ! "$PY" - <<'PY'
import json,time,urllib.request
base="http://127.0.0.1:8766"
for attempt in range(15):
    try:
        def fetch(path):
            with urllib.request.urlopen(base+path,timeout=6) as r:
                return r.read()
        home=fetch("/")
        hive=fetch("/hive")
        local=json.loads(fetch("/api/hive/local"))
        fetch("/api/health")
        assert b'href="/hive"' in home
        assert b'<section class="optin">' not in hive
        assert b'id="consent-status"' in hive
        assert b'id="hive-join"' in hive
        assert b'id="vehicles-chart"' in hive
        assert b'class="globe-photo"' in hive
        print("HOME: PASS | PRIVATE HIVE: PASS")
        print("Coordinator connected:",local["fleet"].get("coordinator_connected"))
        print("Local predictions scored:",local["local"].get("predictions_scored"))
        print("Consent status preserved:",local["hive"].get("contribution"))
        break
    except Exception as error:
        if attempt==14: raise
        time.sleep(2)
PY
then rollback;exit 1;fi
after_home="$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)"
after_server="$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)"
if [[ "$before_home" != "$after_home" || "$before_server" != "$after_server" ]];then
 echo "STOP: Home or web server changed unexpectedly" >&2
 exit 2
fi
echo "[5/5] Building separate real-data PUBLIC static dashboard..."
if bash "$SRC/scripts/hive_public_preview.sh" start;then
  echo "PUBLIC PREVIEW: http://127.0.0.1:8780/"
  if [[ ! -e /etc/systemd/system/ghost-hive-public-refresh.timer ]];then
    sudo bash "$SRC/scripts/hive_public_refresh_timer.sh" install
  else
    echo "Public refresh timer already installed; left untouched."
  fi
else
  echo "WARNING: Private Hive installed; public static preview did not start." >&2
  echo "Check sanitized exporter and restart it separately." >&2
fi
echo "=== EXISTING GHOST SERVICES ==="
systemctl is-active ghost-tesla-ai-web.service ghost-tesla-ai-collector.service
echo "=== HIVE v1 UI INSTALL COMPLETE ==="
echo "Private Hive (existing secure access): /hive"
echo "Public (SSH-loopback preview only): http://127.0.0.1:8780/"
echo "Original Home unchanged. Hive consent unchanged."
echo "Verified backup: $backup"
