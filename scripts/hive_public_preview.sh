#!/usr/bin/env bash
# Safe local static Hive dashboard review: serves TWO sanitized public files.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal ghost user." >&2;exit 2; }
MODE=status
if [[ "$#" -gt 0 ]];then MODE="$1";fi
case "$MODE" in start|refresh|status|stop) ;; *) echo "Usage: hive_public_preview.sh start|refresh|status|stop" >&2;exit 2;; esac
SOURCE="$HOME/genesis-product-source"
DB="$HOME/genesis-product/state/hive-server/hive.sqlite3"
ROOT="$HOME/genesis-product/state/hive-public"
WWW="$ROOT/www"
PID="$ROOT/http.pid"
PY="/opt/ghost-tesla-ai/venv/bin/python"
PORT=8780

test -x "$PY" || { echo "GHOST Python missing" >&2;exit 2; }
test -d "$SOURCE/genesis" || { echo "Hive checkout missing" >&2;exit 2; }
mkdir -p "$ROOT";chmod 700 "$ROOT"

owned_pid(){
  [[ -f "$PID" ]] || return 1
  local p cmd
  p="$(cat "$PID")"
  [[ "$p" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  cmd="$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *"http.server $PORT"* && "$cmd" == *"--directory $WWW"* ]] || return 1
  printf '%s\n' "$p"
}

if [[ "$MODE" == status ]];then
  if p="$(owned_pid)";then echo "HIVE PUBLIC VIEWER RUNNING: $p";else echo "HIVE PUBLIC VIEWER STOPPED";fi
  echo "Local preview: http://127.0.0.1:$PORT/"
  exit 0
fi
if [[ "$MODE" == stop ]];then
  if p="$(owned_pid)";then kill -TERM "$p";echo "STOP REQUESTED: $p";else echo "No owned viewer to stop";fi
  exit 0
fi

[[ -f "$DB" ]] || { echo "Private coordinator database missing" >&2;exit 2; }
[[ ! -L "$WWW" ]] || { echo "Symlink webroot forbidden" >&2;exit 2; }
mkdir -p "$WWW";chmod 700 "$WWW"
tmp="$(mktemp -d "$ROOT/.export.XXXXXXXX")";chmod 700 "$tmp"
trap 'rm -rf "$tmp"' EXIT
cd "$SOURCE"
PYTHONPATH="$SOURCE" "$PY" -m genesis.hive_public --db "$DB" --out "$tmp/candidate.json" >/dev/null
"$PY" "$SOURCE/scripts/hive_public_snapshot_guard.py" --input "$tmp/candidate.json" --output "$tmp/network.json"
test -f "$SOURCE/docs/hive/index.html"
install -m 0600 "$SOURCE/docs/hive/index.html" "$WWW/index.html"
install -m 0600 "$tmp/network.json" "$WWW/network.json"
echo "SAFE PUBLIC FILES REFRESHED"
if [[ "$MODE" == refresh ]];then exit 0;fi
if p="$(owned_pid)";then echo "HIVE ALREADY RUNNING: $p";exit 0;fi
if ss -H -ltn '( sport = :8780 )' | grep -q .;then
 echo "STOP: port 8780 already in use";exit 2
fi
nohup "$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory "$WWW" > "$ROOT/http.log" 2>&1 </dev/null &
echo "$!" > "$PID"
for n in 1 2 3 4 5 6 7 8 9 10;do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/network.json" >/dev/null 2>&1;then
    echo "HIVE PUBLIC LOCAL PREVIEW: http://127.0.0.1:$PORT/"
    echo "Only two approved public files; no source DB or private GHOST API served."
    exit 0
  fi
  sleep .5
done
echo "ERROR: public static server failed health check" >&2
exit 2
