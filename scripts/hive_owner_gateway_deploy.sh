#!/usr/bin/env bash
# Guarded PIN/Hive owner authorization. No Home, model, consent or fleet changes.
set -Eeuo pipefail
[[ "$(id -u)" != "0" ]] || { echo "Run as your normal GHOST user";exit 2; }
MODE=check
if [[ $# -gt 0 ]];then MODE="$1";fi
case "$MODE" in check|install) ;; *) echo "Usage: bash scripts/hive_owner_gateway_deploy.sh check|install";exit 2;;esac
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
LIVE=/opt/ghost-tesla-ai
PY="$LIVE/venv/bin/python"
PATCH="$ROOT/scripts/hive_owner_gateway_update.py"
test -x "$PY"
test -f "$LIVE/web/templates/index.html"
test -f "$LIVE/ghost_tesla_ai/server.py"
test -f "$LIVE/web/templates/hive.html"
cd "$ROOT"
BEFORE_HOME="$(sha256sum "$LIVE/web/templates/index.html"|cut -d' ' -f1)"
BEFORE_SERVER="$(sha256sum "$LIVE/ghost_tesla_ai/server.py"|cut -d' ' -f1)"
BEFORE_HIVE_UI="$(sha256sum "$LIVE/web/templates/hive.html"|cut -d' ' -f1)"
PARENT="$HOME/ghost-hive-owner-backups"
BACKUP="$PARENT/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$PARENT"
chmod 0700 "$PARENT"
changed=0
rollback(){
 local code=$?
 trap - ERR
 if [[ "$changed" == 1 ]];then
   echo "Owner patch verification failed. Rolling back approved files..." >&2
   sudo python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --rollback || \
      echo "Manual checksum review required: $BACKUP" >&2
   sudo systemctl restart ghost-tesla-ai-web.service || true
   if systemctl is-active --quiet ghost-tesla-ai-funnel-gateway.service;then
      sudo systemctl restart ghost-tesla-ai-funnel-gateway.service || true
   fi
 fi
 exit "$code"
}
trap rollback ERR
echo "[1/4] Offline authentication and Hive regression tests..."
"$PY" -m unittest discover -s tests -p 'test_genesis_hive*.py' -q
"$PY" -m unittest discover -s tests -p 'test_release_contract.py' -q
echo "[2/4] Exact source-identity preflight..."
python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --check
if [[ "$MODE" == check ]];then
 echo "HIVE OWNER AUTH CHECK PASS — no source or service changes"
 exit 0
fi
echo "[3/4] Backup and install exactly three reviewed owner API/gateway files..."
sudo -v
sudo python3 "$PATCH" --live "$LIVE" --backup "$BACKUP" --apply
changed=1
sudo systemctl restart ghost-tesla-ai-web.service
if systemctl is-active --quiet ghost-tesla-ai-funnel-gateway.service;then
 sudo systemctl restart ghost-tesla-ai-funnel-gateway.service
 echo "Existing PIN gateway restarted with signed owner proof."
else
 echo "PIN gateway was not running; no new remote listener enabled."
fi
echo "[4/4] Verify API and nonmutating owner proof..."
"$PY" - <<'PY'
import json,sys,time,urllib.error,urllib.request
sys.path.insert(0,"/opt/ghost-tesla-ai")
from ghost_tesla_ai.hive_owner_proof import _key,sign
base="http://127.0.0.1:8766"
for attempt in range(18):
    try:
        with urllib.request.urlopen(base+"/api/hive/local",timeout=4) as response:
            d=json.load(response)
        assert d["scope"]=="LOCAL_GHOST_ONLY"
        assert d["fleet"].get("coordinator_connected") is True
        print("Real Hive enrolled installations:",d["fleet"].get("participating_vehicles"))
        break
    except Exception:
        if attempt==17:raise
        time.sleep(2)
if _key() is not None:
    # Invalid preview lacks a UTC month; 400 confirms authenticated owner path
    # before any upload/consent/revoke action can ever execute.
    body=b"{}"
    origin="https://owner-auth-probe.invalid"
    proof=sign("POST","/api/hive/control/preview",origin,body)
    req=urllib.request.Request(base+"/api/hive/control/preview",method="POST",
        data=body,headers={"Origin":origin,"Content-Type":"application/json",**proof})
    try:
        urllib.request.urlopen(req,timeout=8)
        raise AssertionError("Invalid preview unexpectedly succeeded")
    except urllib.error.HTTPError as response:
        result=json.load(response)
        assert response.code==400 and result.get("error")=="SELECT_A_VALID_UTC_MONTH",(response.code,result)
    print("Signed PIN-to-Hive owner proof: PASS (no changes)")
else:
    print("PIN setup not found; sign-in will activate when PIN is configured.")
PY
test "$(sha256sum "$LIVE/web/templates/index.html"|cut -d' ' -f1)" = "$BEFORE_HOME"
test "$(sha256sum "$LIVE/ghost_tesla_ai/server.py"|cut -d' ' -f1)" = "$BEFORE_SERVER"
test "$(sha256sum "$LIVE/web/templates/hive.html"|cut -d' ' -f1)" = "$BEFORE_HIVE_UI"
changed=0
trap - ERR
echo "HIVE OWNER ACCESS INSTALL PASS"
echo "Classic Home/server, Fleet UI and consent unchanged."
echo "Rollback manifest: $BACKUP/latest.json"
