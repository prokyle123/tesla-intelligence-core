#!/usr/bin/env bash
# Explicit owner opt-in: private tailnet HTTPS through already PIN-gated GHOST.
# Never enable public Funnel, open router/firewall ports or expose the raw 8766.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as your normal installed GHOST account.";exit 2; }
CODE=/opt/ghost-tesla-ai
PY="$CODE/venv/bin/python"
PIN=/var/lib/ghost-tesla-ai/funnel_pin.json
test -x "$PY"
test -f "$CODE/ghost_tesla_ai/hive_owner_proof.py" || {
 echo "Install the reviewed signed Hive owner gateway patch first.";exit 2;
}
command -v tailscale >/dev/null || {
 echo "Tailscale not installed. Connect it on the Pi and your phone/PC first.";exit 2;
}
if ! sudo tailscale status >/dev/null 2>&1;then
 echo "Tailscale is installed but not connected. Run sudo tailscale up first.";exit 2;
fi
echo "=== 1. PIN-PROTECTED GHOST OWNER ACCESS ==="
if [[ ! -f "$PIN" ]];then
 echo "Create a PIN once. The installer never writes or displays it in logs."
 env PYTHONPATH="$CODE" "$PY" -m ghost_tesla_ai.funnel_pin_setup
else
 echo "Existing private PIN record preserved."
fi
echo "=== 2. PRIVATE LOOPBACK GATEWAY ==="
sudo systemctl enable --now ghost-tesla-ai-funnel-gateway.service
# A newly restarted Python gateway may need a few seconds to import Flask and
# bind its loopback socket. Avoid misdiagnosing startup as an auth failure.
READY=0
for attempt in $(seq 1 24);do
  STATUS="$(curl --noproxy '*' -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8777/__ghost_auth/login 2>/dev/null || true)"
  if [[ "$STATUS" == 200 ]];then READY=1;break;fi
  sleep 1
done
if [[ "$READY" != 1 ]];then
  echo "PIN gateway did not become healthy on local port 8777." >&2
  echo "Service state:" >&2
  sudo systemctl --no-pager --full status ghost-tesla-ai-funnel-gateway.service >&2 || true
  echo "Recent gateway log (no secret values):" >&2
  sudo journalctl --no-pager -u ghost-tesla-ai-funnel-gateway.service -n 45 --output=cat >&2 || true
  echo "Existing Serve/Funnel settings were NOT changed." >&2
  exit 2
fi
echo "Gateway PIN login verified on Pi loopback."
echo "=== 3. EXISTING SERVE/FUNNEL CONFIGURATION ==="
STATUS="$(sudo tailscale serve status --json 2>/dev/null || true)"
if [[ -z "$STATUS" ]];then
 echo "Cannot safely inspect existing Tailscale Serve configuration; no changes made."
 exit 2
fi
# Both Serve and Funnel share tailnet HTTPS server state; never overwrite an
# existing listener, public exposure, or user-configured domains automatically.
if ! printf '%s' "$STATUS" | "$PY" -c '
import json,sys
d=json.load(sys.stdin)
assert isinstance(d,dict)
if any(d.get(k) for k in ("TCP","Web","AllowFunnel","Foreground")):
    sys.exit(1)
';then
 echo "Existing Tailscale Serve/Funnel config detected."
 echo "Nothing was overwritten. Use your already configured PIN-protected HTTPS URL if it points to 127.0.0.1:8777."
 sudo tailscale serve status || true
 exit 0
fi
echo "=== 4. ENABLE PRIVATE HTTPS FOR AUTHENTICATED TAILNET USERS ONLY ==="
sudo tailscale serve --bg http://127.0.0.1:8777
sudo tailscale serve status
echo "HIVE PRIVATE HTTPS SETUP COMPLETE."
echo "Open the HTTPS tailnet Serve address printed above on your connected phone/PC."
echo "Sign in once with the PIN, then manage Hive without any SSH tunnel."
echo "Never point a public Funnel directly at 8766."
