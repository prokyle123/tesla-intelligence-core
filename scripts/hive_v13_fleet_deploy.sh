#!/usr/bin/env bash
# Hive v1.3: update ONLY reviewed local Hive module and private Fleet UI.
# Never change Classic Home, neural models, telemetry, coordinator or consent.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal ghost user" >&2;exit 2; }
MODE="${1:-check}"
case "$MODE" in check|install) ;; *) echo "Usage: bash scripts/hive_v12_deploy.sh check|install" >&2;exit 2;; esac
SRC="$(cd "$(dirname "$0")/.." && pwd -P)"
LIVE=/opt/ghost-tesla-ai
PY="$LIVE/venv/bin/python"
PATCH="$SRC/scripts/ghost_hive_update.py"
BACKUP_PARENT="$HOME/ghost-hive-ui-backups"
BACKUP="$BACKUP_PARENT/v13-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test -x "$PY" && test -f "$LIVE/web/templates/index.html" && test -f "$LIVE/ghost_tesla_ai/server.py" || {
  echo "STOP: installed Classic GHOST not found" >&2;exit 2;
}
before_home="$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)"
before_server="$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)"
mkdir -p "$BACKUP_PARENT"
chmod 0700 "$BACKUP_PARENT"
changed=0
rollback(){
  rc=$?
  trap - ERR
  if [[ "$changed" == 1 ]];then
    echo "HIVE v1.3 update failed; restoring original Hive-only files..." >&2
    if sudo python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --rollback;then
      sudo systemctl restart ghost-tesla-ai-web.service || true
      echo "Previous Hive-only source restored; inspect $BACKUP" >&2
    else
      echo "Automatic rollback refused; inspect $BACKUP (DO NOT OVERWRITE HOME)" >&2
    fi
  fi
  exit "$rc"
}
trap rollback ERR

echo "[1/4] Offline Hive regression tests..."
cd "$SRC"
"$PY" -m unittest discover -s tests -p 'test_genesis_hive*.py' -q
"$PY" -m unittest discover -s tests -p 'test_release_contract.py' -q
echo "[2/4] Exact-hash Hive-only upgrade preflight..."
python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --check
if [[ "$MODE" == check ]];then
  echo "HIVE v1.3 PRECHECK PASS — no files or services modified"
  exit 0
fi

echo "[3/4] Backup and install only approved Hive files..."
sudo -v
sudo python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --apply
changed=1
sudo systemctl restart ghost-tesla-ai-web.service
echo "[4/4] Verify localhost API and Fleet UI; refresh sanitized PUBLIC files..."
"$PY" - <<'PY'
import json,time,urllib.request
url="http://127.0.0.1:8766/api/hive/local"
for attempt in range(15):
    try:
        with urllib.request.urlopen(url,timeout=4) as resp:
            data=json.load(resp)
        assert data.get("scope")=="LOCAL_GHOST_ONLY"
        windows=data.get("recent_quality")
        assert isinstance(windows,dict)
        for period in ("7d","30d"):
            record=windows.get(period)
            assert isinstance(record,dict)
            assert isinstance(record.get("temp_predictions_scored"),int)
            assert record.get("temp_predictions_scored")>=0
        print("Hive private rolling-quality API: PASS")
        print("7d forecasts:",windows["7d"]["temp_predictions_scored"])
        print("30d forecasts:",windows["30d"]["temp_predictions_scored"])
        print("Consent unchanged:",data["hive"]["contribution"])
        fleet=data.get("fleet") or {}
        if fleet.get("coordinator_connected") is True:
            count=fleet.get("participating_vehicles")
            assert type(count) is int and count>=0, "Connected Hive must expose a real overall enrolled count"
            print("Coordinator-confirmed enrolled reporting installations:",count)
            print("Qualified broad regions:",len(fleet.get("regions") or []))
        else:
            print("Coordinator unavailable; leaving contributor count unknown.")
        with urllib.request.urlopen("http://127.0.0.1:8766/hive",timeout=4) as page:
            html=page.read().decode("utf-8")
        assert 'window.hiveReporting=Number.isInteger(fleet.participating_vehicles)' in html
        assert 'Overall enrollment · not a monthly count' in html
        assert 'Your selected broad region (private view)' in html
        print("Hive single-reporter Fleet UI: PASS")
        break
    except Exception:
        if attempt==14:raise
        time.sleep(2)
PY
bash "$SRC/scripts/hive_public_preview.sh" refresh
test "$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)" = "$before_home"
test "$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)" = "$before_server"
trap - ERR
changed=0
echo "HIVE v1.3 FLEET DISPLAY INSTALL PASS — original Home/server unchanged"
echo "Rollback manifest: $BACKUP/latest.json"
echo "Public viewer snapshot refreshed; no contribution settings changed"
