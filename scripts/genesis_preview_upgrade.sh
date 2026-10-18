#!/usr/bin/env bash
# Upgrade only the GENESIS localhost preview; never Classic GHOST.
set -Eeuo pipefail

fail(){ echo "GENESIS PREVIEW UPGRADE STOP: $*" >&2; exit 2; }
[[ "$EUID" -ne 0 ]] || fail "Do not run as root."
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
BASE="$HOME/genesis-product"
STATE="$BASE/state"
PID_FILE="$STATE/dashboard.pid"
[[ -d "$ROOT/.git" ]] || fail "Run this script from a checked-out development repository."
[[ -d "$STATE" && -L "$BASE/current" ]] || fail "Stage an initial GENESIS preview first."
[[ -f "/var/lib/ghost-tesla-ai/ghost_ai.sqlite3" ]] || fail "Classic telemetry source not found; nothing changed."

if [[ -x /opt/ghost-tesla-ai/venv/bin/python ]] \
   && /opt/ghost-tesla-ai/venv/bin/python -c "import flask" 2>/dev/null; then
  PY=/opt/ghost-tesla-ai/venv/bin/python
elif /usr/bin/python3 -c "import flask" 2>/dev/null; then
  PY=/usr/bin/python3
else
  fail "No working Flask Python interpreter; nothing changed."
fi

echo "[1/5] Checking isolated GENESIS preview..."
OLD=""
if [[ -f "$PID_FILE" ]]; then
  candidate="$(cat "$PID_FILE")"
  if [[ "$candidate" =~ ^[0-9]+$ ]] && kill -0 "$candidate" 2>/dev/null; then
    argv="$(tr '\0' ' ' < "/proc/$candidate/cmdline" 2>/dev/null || true)"
    if [[ "$argv" == *"genesis.workspace"* && "$argv" == *"--port 8767"* \
       && "$argv" == *"--data-dir $STATE"* ]]; then
      OLD="$candidate"
      echo "Existing owned GENESIS viewer PID: $OLD"
    else
      fail "Viewer PID file points to an unexpected process; refusing to kill it."
    fi
  fi
fi
if [[ -z "$OLD" ]] && ss -H -ltn '( sport = :8767 )' | grep -q .; then
  fail "Local port 8767 is occupied by an unverified process; no changes made."
fi

echo "[2/5] Verifying new GENESIS tests before switching..."
cd "$ROOT"
"$PY" -m unittest discover -s tests -p 'test_genesis*.py' -q \
  > "$STATE/upgrade-tests.log" 2>&1 || {
    tail -50 "$STATE/upgrade-tests.log" >&2
    fail "New research and dashboard tests did not pass; old viewer unchanged."
  }

echo "[3/5] Staging versioned GENESIS-only files..."
bash "$ROOT/scripts/genesis_stage_preview.sh" stage

echo "[4/5] Restarting only verified GENESIS preview process..."
if [[ -n "$OLD" ]]; then
  kill -TERM "$OLD"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$OLD" 2>/dev/null || break
    sleep .5
  done
  if kill -0 "$OLD" 2>/dev/null; then
    fail "Previous viewer did not stop; not starting another."
  fi
fi
if ss -H -ltn '( sport = :8767 )' | grep -q .; then
  fail "Port 8767 did not become available. No other process will be killed."
fi

cd "$BASE/current"
nohup "$PY" -m genesis.workspace --data-dir "$STATE" --port 8767 \
  > "$STATE/dashboard.log" 2>&1 </dev/null &
NEW_PID="$!"
printf '%s\n' "$NEW_PID" > "$PID_FILE"

echo "[5/5] Verifying upgraded dashboard and API..."
OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if "$PY" - <<'PY'
import json,sys,urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8767/api/genesis/health",timeout=2) as r:
        response=json.load(r)
    assert response.get("ok") is True
    assert response.get("version") == "0.4.0-preview"
    assert response.get("research_only") is True
    assert response.get("production_changes") is False
except Exception:
    # The new process may still be binding localhost; retry without a traceback.
    sys.exit(1)
PY
  then
    OK=1
    echo "GENESIS viewer ready after readiness attempt $i"
    break
  fi
  sleep .5
done
if [[ "$OK" -ne 1 ]]; then
  echo "New preview did not pass health. Existing research data is preserved." >&2
  tail -40 "$STATE/dashboard.log" >&2
  fail "Use scripts/genesis_stage_preview.sh rollback to switch code to the previous stage."
fi

echo "[5/5] Confirming real research diagnostic endpoints..."
"$PY" - <<'PY'
import json, urllib.request
for endpoint in ("prediction-quality","thermal-context","paired-baseline","prospective-watch"):
    url="http://127.0.0.1:8767/api/genesis/"+endpoint
    with urllib.request.urlopen(url,timeout=30) as response:
        doc=json.load(response)
    assert doc.get("scope")=="LOCAL_GHOST_ONLY",endpoint
    assert doc.get("production_changes") is False,endpoint
    assert doc.get("network_uploads") is False,endpoint
    assert doc.get("can_promote") is False,endpoint
    assert isinstance(doc.get("status"),str),endpoint
    if endpoint=="prospective-watch":
        assert doc["status"] in ("NOT_FROZEN","AWAITING_FUTURE_EVIDENCE",
                                  "POST_FREEZE_EVIDENCE_AVAILABLE",
                                  "CAPACITY_REVIEW_REQUIRED"),doc["status"]
    print(endpoint,":",doc["status"])
PY

echo
echo "GENESIS v0.5 RESEARCH PREVIEW UPGRADE PASS"
echo "Viewer PID: $NEW_PID"
echo "Local URL: http://127.0.0.1:8767/genesis"
echo "Existing product history preserved in: $STATE"
echo "Classic GHOST processes and predictions untouched."
