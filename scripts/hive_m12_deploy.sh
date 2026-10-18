#!/usr/bin/env bash
# M12 independent Fleet Intelligence: one validated release; no collector/model changes.
set -Eeuo pipefail
MODE="${1:-check}"
case "$MODE" in check|install) ;; *) echo "Usage: bash scripts/hive_m12_deploy.sh check|install"; exit 2;;esac
[[ "$(id -u)" != 0 ]] || { echo "Run as the regular ghost account"; exit 2; }
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
PY=/opt/ghost-tesla-ai/venv/bin/python
STATE="$HOME/genesis-product/state"
WATCH="$STATE/prospective-truth-watch.json"
CAND="$STATE/prospective-challenger.json"
test -x "$PY"
test -f "$WATCH" && test -f "$CAND"
W_SHA="$(sha256sum "$WATCH"|cut -d' ' -f1)"
C_SHA="$(sha256sum "$CAND"|cut -d' ' -f1)"
REV="$(git rev-parse --verify HEAD)"
test -z "$(git status --porcelain)" || {
 echo "STOP: Uncommitted changes; refusing managed install"; exit 2;
}
echo "=== HIVE M12 SOURCE: $REV ==="
echo "[1/5] Full isolated GENESIS/Hive offline regression..."
"$PY" -m unittest discover -s tests -p 'test_genesis*.py' -q   >/tmp/ghost-hive-m12-tests.log 2>&1 || {
    tail -100 /tmp/ghost-hive-m12-tests.log
    exit 1
  }
"$PY" -m unittest discover -s tests -p 'test_release_contract.py' -q   >>/tmp/ghost-hive-m12-tests.log 2>&1 || {
    tail -100 /tmp/ghost-hive-m12-tests.log
    exit 1
  }
echo "OFFLINE TESTS PASS"
echo "[2/5] Validate managed coordinator and exact installed owner files..."
python3 scripts/hive_coordinator_managed_upgrade.py check
bash scripts/hive_owner_gateway_deploy.sh check
if [[ "$MODE" == check ]];then
 echo "HIVE M12 CHECK PASS — source/services/databases unchanged"
 exit 0
fi
echo "[3/5] Stage reviewed isolated GENESIS reader..."
bash scripts/genesis_preview_upgrade.sh
echo "[4/5] Upgrade only managed coordinator and Hive owner UI..."
python3 scripts/hive_coordinator_managed_upgrade.py install
bash scripts/hive_owner_gateway_deploy.sh install
echo "[5/5] Verify private independent comparison security and production isolation..."
"$PY" - <<'PY'
import json, sys, urllib.error, urllib.request
sys.path.insert(0,"/opt/ghost-tesla-ai")
from ghost_tesla_ai.hive_owner_proof import _key,sign
base="http://127.0.0.1:8766"
with urllib.request.urlopen(base+"/api/hive/local",timeout=8) as response:
    local=json.load(response)
assert local["scope"]=="LOCAL_GHOST_ONLY"
assert local["fleet"]["coordinator_connected"] is True
print("Current enrolled reporting installations:",
      local["fleet"]["participating_vehicles"])
assert local["fleet"]["participating_vehicles"]>=1
for url,method,data,expected in (
    (base+"/api/hive/peer-comparison","GET",None,404),
    (base+"/api/hive/control/peer-compare","POST",b"{}",403),
    ("http://127.0.0.1:8778/v1/member-comparison","GET",None,401),
):
    req=urllib.request.Request(url,method=method,data=data,
       headers={"Origin":"https://hive-check.invalid",
                "Content-Type":"application/json"})
    try:
        urllib.request.urlopen(req,timeout=7)
        raise AssertionError("Unexpected anonymous comparison access: "+url)
    except urllib.error.HTTPError as err:
        assert err.code==expected,(url,err.code,expected)
print("Anonymous peer data access: BLOCKED")
if _key() is not None:
    path="/api/hive/control/peer-compare"
    body=b"{}"
    origin="https://hive-check.invalid"
    headers={"Origin":origin,"Content-Type":"application/json",
             **sign("POST",path,origin,body)}
    req=urllib.request.Request(base+path,data=body,
                               method="POST",headers=headers)
    with urllib.request.urlopen(req,timeout=10) as response:
        peer=json.load(response)
    assert peer["schema"]=="ghost-hive-independent-comparison-v1"
    assert peer.get("self_excluded_from_peers") is True
    assert peer["status"] in (
        "AWAITING_LOCAL_MONTHLY_REPORT",
        "AWAITING_PUBLISHABLE_PEERS",
        "COMPARISON_AVAILABLE",
        "NOT_ENROLLED","PEER_SERVICE_UNAVAILABLE")
    print("Authenticated, read-only member comparison:",peer["status"])
    if peer.get("latest"):
        print("Independent peer UTC month:",peer["latest"].get("month"))
        print("Independent peer installs:",peer["latest"].get("peer_installations"))
else:
    print("PIN gateway key not set; authenticated live probe skipped.")
PY
test "$W_SHA" = "$(sha256sum "$WATCH"|cut -d' ' -f1)"
test "$C_SHA" = "$(sha256sum "$CAND"|cut -d' ' -f1)"
systemctl is-active --quiet ghost-hive-coordinator.service
systemctl is-active --quiet ghost-tesla-ai-web.service
systemctl is-active --quiet ghost-tesla-ai-collector.service
echo "=== HIVE M12 INSTALL PASS — Classic GHOST and research freezes preserved ==="
