# Remote access

## Private Tailscale access

The simplest remote setup is to install Tailscale on the Pi and access GHOST through the Pi's Tailscale IP on port `8766`. This stays inside your tailnet.

## Optional public Funnel with PIN gateway

GHOST includes a small PIN gateway that listens only on `127.0.0.1:8777`. The intended path is:

```text
Internet HTTPS -> Tailscale Funnel -> 127.0.0.1:8777 -> PIN gateway -> 127.0.0.1:8766
```

Configure a PIN:

```bash
cd /opt/ghost-tesla-ai
./venv/bin/python -m ghost_tesla_ai.funnel_pin_setup
sudo systemctl enable --now ghost-tesla-ai-funnel-gateway.service
sudo tailscale funnel --bg http://127.0.0.1:8777
tailscale funnel status
```

The PIN itself is not stored in plaintext. The PIN record uses `scrypt` plus a random salt, and the browser receives an HttpOnly/Secure session cookie after successful authentication.

### Important

Do **not** point a public Funnel directly at port `8766` if you expect the PIN gateway to protect it.
