#!/usr/bin/env bash
# Independent localhost Hive preview; no production changes.
set -Eeuo pipefail
[[ "$EUID" -ne 0 ]] || { echo "Run as normal user." >&2; exit 2; }
MODE="status"
if [[ "$#" -gt 0 ]]; then MODE="$1"; fi
case "$MODE" in start|status|stop) ;; *) echo "Usage: $0 start|status|stop" >&2;exit 2;; esac
BASE="$HOME/genesis-product"
STATE="$BASE/state/hive-server"
APP="$BASE/current"
PID="$STATE/server.pid"
DB="$STATE/hive.sqlite3"
PORT=8778
PY="/opt/ghost-tesla-ai/venv/bin/python"

[[ -d "$APP/genesis" ]] || { echo "Stage GENESIS first." >&2;exit 2; }
[[ -x "$PY" ]] || { echo "Flask-capable Python not found." >&2;exit 2; }
mkdir -p "$STATE"
chmod 700 "$STATE"

owned_pid() {
  [[ -f "$PID" ]] || return 1
  local value cmd
  value="$(cat "$PID")"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$value" 2>/dev/null || return 1
  cmd="$(tr '\0' ' ' < "/proc/$value/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *"genesis.hive_server"* && "$cmd" == *"--port $PORT"* && "$cmd" == *"--db $DB"* ]] || return 1
  printf '%s\n' "$value"
}

case "$MODE" in
 status)
   if p="$(owned_pid)"; then
     echo "HIVE LOCAL PREVIEW RUNNING: PID $p"
     curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" || true
     echo
   else
     echo "HIVE LOCAL PREVIEW NOT RUNNING"
   fi
   echo "Dashboard via SSH tunnel: http://127.0.0.1:$PORT/hive"
   exit 0
   ;;
 stop)
   if p="$(owned_pid)"; then
     kill -TERM "$p"
     echo "Requested stop for verified Hive preview PID $p"
   else
     echo "No owned Hive server process to stop."
   fi
   exit 0
   ;;
esac

if p="$(owned_pid)"; then
  echo "HIVE ALREADY RUNNING: PID $p"
  exit 0
fi
if ss -H -ltn '( sport = :8778 )' | grep -q .; then
  echo "STOP: Port 8778 belongs to another process; nothing killed." >&2
  exit 2
fi
cd "$APP"
"$PY" -m genesis.hive_server --db "$DB" init
nohup "$PY" -m genesis.hive_server --db "$DB" --port "$PORT" serve \
    > "$STATE/server.log" 2>&1 </dev/null &
NEW="$!"
printf '%s\n' "$NEW" > "$PID"
OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/health" |
     grep -q '"ok":true'; then
    OK=1;break
  fi
  sleep .5
done
if [[ "$OK" -ne 1 ]]; then
  echo "Hive did not pass startup health:" >&2
  tail -20 "$STATE/server.log" >&2
  exit 2
fi
echo "HIVE PRIVATE ANALYTICS STARTED"
echo "PID: $NEW"
echo "URL (SSH tunnel required): http://127.0.0.1:$PORT/hive"
echo "Demo toggle available. No vehicle data sent; no client opt-in enabled."
