# Remote access

Tesla Intelligence Core can be used entirely on your local network. Remote access is optional.

For the in-car use case, see **[Tesla in-car browser access](TESLA_BROWSER.md)**. On the development setup, the Tesla browser would not load the Pi's local/private URL, while the PIN-protected public HTTPS Funnel route did work. Vehicle/software/network behavior can vary.

> The dashboard can contain personal vehicle history. Treat it accordingly.

## Option 1: private Tailscale access

This is the simplest remote approach.

Install/connect Tailscale on the Pi, then access:

```text
http://TAILSCALE_IP:8766
```

That route stays inside your tailnet but is **read-only for Hive contribution settings** unless separate owner proof is supplied. Do not mistake private-network reachability for authenticated ownership.

### Recommended: private HTTPS Tailscale Serve for PIN-authenticated Hive controls

On reviewed GENESIS/Hive owner-enabled source, run:

```bash
bash scripts/hive_owner_gateway_deploy.sh check
bash scripts/hive_owner_gateway_deploy.sh install
bash scripts/hive_owner_private_https_setup.sh
```

Tailscale must be installed and connected on the Pi and your phone/PC. The setup reuses the existing GHOST PIN, or prompts to create one once. It does not create a public Funnel and will not overwrite an existing Serve/Funnel route. It prints a **private HTTPS** tailnet URL. Open that URL, enter the PIN, then manage Hive at `/hive` normally: join, change sharing, pause or revoke enrollment. No SSH tunnel or browser-injected API token is needed.

If a separately configured PIN-protected Funnel already exists, retain its approved HTTPS URL instead. **Never route Funnel directly to 8766.** Only the loopback PIN gateway at 8777 can sign short-lived owner actions.

## Option 2: public Tailscale Funnel + PIN gateway

Tesla Intelligence Core includes a small PIN gateway intended for optional Funnel access.

Expected path:

```text
Internet HTTPS
      ↓
Tailscale Funnel
      ↓
127.0.0.1:8777
      ↓
PIN gateway
      ↓
127.0.0.1:8766
```

### Configure the PIN

```bash
cd /opt/ghost-tesla-ai
./venv/bin/python -m ghost_tesla_ai.funnel_pin_setup
```

Do not paste the PIN into logs, screenshots or GitHub issues.

### Start the gateway

```bash
sudo systemctl enable --now ghost-tesla-ai-funnel-gateway.service
```

### Point Funnel at the gateway

```bash
sudo tailscale funnel --bg http://127.0.0.1:8777
```

### Verify

```bash
tailscale funnel status
curl -I http://127.0.0.1:8777/
sudo systemctl status ghost-tesla-ai-funnel-gateway.service --no-pager
```

## Important

Do **not** configure public Funnel traffic directly to:

```text
8766
```

if you expect the PIN gateway to protect the dashboard.

The raw dashboard/API should be treated as private LAN/tailnet access.

## PIN storage

The PIN itself is not stored as plaintext.

The gateway record uses:
- `scrypt`;
- random salt;
- session signing secret.

Runtime file:

```text
/var/lib/ghost-tesla-ai/funnel_pin.json
```

The authenticated browser receives a Secure / HttpOnly session cookie.

## Troubleshooting

Gateway logs:

```bash
sudo journalctl -u ghost-tesla-ai-funnel-gateway.service -n 100 --no-pager
```

Dashboard check:

```bash
curl -fsS http://127.0.0.1:8766/api/health
```

Gateway check:

```bash
curl -I http://127.0.0.1:8777/
```

Funnel status:

```bash
tailscale funnel status
```

See also: [Troubleshooting](TROUBLESHOOTING.md).
