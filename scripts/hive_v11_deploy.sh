#!/usr/bin/env bash
# GHOST Hive v1.1 safe coordinator + UI + public snapshot rollout.
# Never touch Classic GHOST Home, neural models, collector, or owner consent.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as ordinary Ghost SSH user" >&2; exit 2; }
MODE=check
if [[ "$#" -gt 0 ]];then MODE="$1";fi
case "$MODE" in check|install) ;; *) echo "Usage: hive_v11_deploy.sh check|install" >&2;exit 2;; esac
SRC="$(cd "$(dirname "$0")/.." && pwd -P)"
LIVE=/opt/ghost-tesla-ai
STATE="$HOME/genesis-product/state/hive-client"
test -f "$STATE/real-consent.json" || { echo "STOP: existing consent state unavailable" >&2;exit 2; }
old_home="$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)"
old_server="$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)"
echo "[1] Full Hive offline tests and Hive-owned exact-hash check..."
bash "$SRC/scripts/hive_v1_ui_deploy.sh" check
if [[ "$MODE" == check ]];then
  echo "HIVE v1.1 PRECHECK PASS; no production services changed."
  exit 0
fi
echo "[2] Staging versioned isolated GENESIS/Hive backend..."
bash "$SRC/scripts/genesis_stage_preview.sh" stage
echo "[3] Restarting ONLY verified independent Hive server..."
bash "$SRC/scripts/hive_preview.sh" stop
free=0
for try in $(seq 1 24);do
  if ! ss -H -ltn '( sport = :8778 )' | grep -q .;then free=1;break;fi
  sleep .5
done
if [[ "$free" != 1 ]];then
  echo "STOP: Hive coordinator port still in use; no unowned processes stopped" >&2
  exit 2
fi
if ! bash "$SRC/scripts/hive_preview.sh" start;then
  echo "New Hive coordinator failed; restoring previous staged release..." >&2
  bash "$SRC/scripts/genesis_stage_preview.sh" rollback || true
  bash "$SRC/scripts/hive_preview.sh" start || true
  exit 2
fi
echo "[4] Safely upgrading only private Hive-owned files, plus public preview..."
bash "$SRC/scripts/hive_v1_ui_deploy.sh" install
echo "[5] Validating independent Hive and local Classic analytics..."
/opt/ghost-tesla-ai/venv/bin/python - <<'PY'
import json,urllib.request
def read(url):
 with urllib.request.urlopen(url,timeout=10) as response:
  return json.load(response)
hub=read("http://127.0.0.1:8778/v1/public-network")
local=read("http://127.0.0.1:8766/api/hive/local")
assert hub["schema"]=="ghost-hive-public-v1"
assert isinstance(hub["regions"],list)
assert local["fleet"]["coordinator_connected"] is True
assert local["fleet"]["participating_vehicles"]==hub["reporting_nodes"]
assert local["local"]["predictions_scored"] is not None
print("Coordinator connected:",local["fleet"]["coordinator_connected"])
print("Local scored predictions:",local["local"]["predictions_scored"])
print("Reporting nodes:",hub["reporting_nodes"])
print("Published broad regions:",len(hub["regions"]))
print("Current consent:",local["hive"]["contribution"])
PY
test "$(sha256sum "$LIVE/web/templates/index.html" | cut -d' ' -f1)" = "$old_home"
test "$(sha256sum "$LIVE/ghost_tesla_ai/server.py" | cut -d' ' -f1)" = "$old_server"
echo "=== HIVE v1.1 CHECKS PASS: original GHOST Home unchanged ==="
