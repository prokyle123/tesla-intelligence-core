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
sudo systemctl restart ghost-tesla-ai-funnel-gateway.service
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8777/__ghost_auth/login)" = 200
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
