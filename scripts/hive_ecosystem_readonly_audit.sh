#!/usr/bin/env bash
# Strictly read-only production topology snapshot; print no PINs or tokens.
set -u
ROOT="$HOME/genesis-product-source"
COORD="$HOME/genesis-product/state/hive-server/hive.sqlite3"
echo "=== HIVE ECOSYSTEM SAFE READ-ONLY AUDIT ==="
echo "Date UTC: $(date -u +%FT%TZ)"
echo "Git source: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo UNKNOWN)"
echo "Staged GENESIS revision:"
readlink -f "$HOME/genesis-product/current" || true
echo "Services:"
for unit in ghost-tesla-ai-web.service ghost-tesla-ai-collector.service \
  ghost-tesla-ai-funnel-gateway.service ghost-hive-hourly.timer \
  ghost-hive-public-refresh.timer;do
  printf '%s: ' "$unit"
  systemctl is-active "$unit" 2>/dev/null || true
done
echo
echo "Listening ports and process names (no argv secrets):"
sudo ss -H -lntp 2>/dev/null | grep -E ':8766|:8767|:8777|:8778|:8780' || true
echo
echo "Gateway health:"
curl --noproxy '*' --max-time 4 -sS \
  -o /dev/null -w 'http://127.0.0.1:8777/__ghost_auth/login -> %{http_code}\n' \
  http://127.0.0.1:8777/__ghost_auth/login || true
echo "Coordinator public endpoint (sanitized):"
python3 - <<'PY'
import json,urllib.request
for u in ("http://127.0.0.1:8778/health",
          "http://127.0.0.1:8778/v1/public-network"):
 try:
  with urllib.request.urlopen(u,timeout=3) as r:d=json.load(r)
  if "public-network" in u:
   print("reporters",d.get("reporting_nodes"),
         "public_regions",len(d.get("regions",[])),
         "source",d.get("source"))
  else:
   print("health",d.get("ok"),"stage",d.get("stage"))
 except Exception as e:print("not available:",type(e).__name__)
PY
echo "Coordinator DB schema (no participant data or credentials):"
python3 - "$COORD" <<'PY'
import sqlite3,sys,pathlib
p=pathlib.Path(sys.argv[1])
if not p.is_file():
 print("Coordinator DB not found at conventional path");sys.exit(0)
try:
 with sqlite3.connect("file:"+str(p)+"?mode=ro",uri=True) as c:
  c.execute("PRAGMA query_only=ON")
  cols=[x[1] for x in c.execute("PRAGMA table_info(region_consents)")]
  print("regional consent table present:",bool(cols))
  print("single-member public option installed:","public_listing" in cols)
  print("enrolled overall:",c.execute("SELECT COUNT(*) FROM participants WHERE enabled=1").fetchone()[0])
except Exception as e:print("Schema read unavailable:",type(e).__name__)
PY
echo "Tailscale private/public routing:"
sudo tailscale serve status || true
sudo tailscale funnel status || true
echo "Gateway recent status (secrets not emitted):"
sudo systemctl --no-pager --plain is-active ghost-tesla-ai-funnel-gateway.service || true
echo "=== AUDIT END ==="
