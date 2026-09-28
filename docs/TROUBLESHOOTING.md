# Troubleshooting

## Start with status

```bash
ghost-ai status
```

Then check:

```bash
systemctl status ghost-tesla-ai-web.service --no-pager
systemctl status ghost-tesla-ai-collector.service --no-pager
systemctl status ghost-tesla-ai-intelligence.timer --no-pager
systemctl status ghost-tesla-ai-neural.timer --no-pager
```

## Dashboard does not load

Local API test:

```bash
curl -v http://127.0.0.1:8766/api/health
```

Dashboard logs:

```bash
sudo journalctl -u ghost-tesla-ai-web.service -n 100 --no-pager
```

Check the configured port:

```bash
grep '^GHOST_AI_PORT=' /etc/ghost-tesla-ai/ghost.env
```

## No telemetry / stale telemetry

Collector logs:

```bash
sudo journalctl -u ghost-tesla-ai-collector.service -n 120 --no-pager
```

Check source mode:

```bash
grep '^SOURCE_MODE=' /etc/ghost-tesla-ai/ghost.env
```

For Tessie, verify the token file exists without printing its contents:

```bash
sudo ls -l /etc/ghost-tesla-ai/tessie.token
```

For TeslaMate, verify the Pi can reach the MQTT broker.

## Historical backfill

If bootstrap was started during install:

```bash
tail -f /var/lib/ghost-tesla-ai/bootstrap.log
```

## Learning looks thin

A fresh system needs evidence.

Check:
- telemetry is arriving;
- timezone is correct;
- real drive events exist;
- backfill is still running or completed;
- intelligence timer is active.

Run an intelligence cycle manually:

```bash
ghost-ai intelligence
```

## Neural model is not ready

Check:

```bash
sudo journalctl -u ghost-tesla-ai-neural.service -n 120 --no-pager
```

A new install may not yet have enough sequence data.

## Tailscale private access works but Funnel does not

Gateway status:

```bash
sudo systemctl status ghost-tesla-ai-funnel-gateway.service --no-pager
```

Gateway local response:

```bash
curl -I http://127.0.0.1:8777/
```

Funnel:

```bash
tailscale funnel status
```

Make sure Funnel targets `127.0.0.1:8777`, not the raw dashboard port.

## Installer fails

Re-run the installer and keep the exact error text:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/tesla-intelligence-core/main/install.sh)
```

Before posting logs publicly, redact VINs, coordinates, tokens and private addresses.

## Full reset

Use:

```bash
./uninstall.sh
```

and choose to remove learned data/config when prompted.

This is destructive. Back up anything you want to keep first.
