# Installation

This guide covers a fresh Tesla Intelligence Core installation.

> Internal package/service names still use the original `ghost_tesla_ai` / `ghost-tesla-ai-*` names for compatibility.

## Recommended platform

- Raspberry Pi 5 recommended
- 64-bit Raspberry Pi OS or Debian
- Internet access during installation
- Python 3.11+
- Tessie account/token **or** an existing TeslaMate MQTT broker

## Before you start

For a Tessie install, have your Tessie API token ready.

For TeslaMate, have the MQTT broker host/port and TeslaMate car ID ready. If the broker uses credentials or TLS, have those details too.

Make sure the Pi timezone matches the timezone in which you normally use the car. Departure learning works in local wall-clock time.

## Interactive one-line install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/tesla-intelligence-core/main/install.sh)
```

The script downloads the repository to a temporary directory and runs the interactive installer.

## What the installer does

The installer:

1. checks the Linux user and platform;
2. asks for timezone;
3. asks for Tessie or TeslaMate;
4. collects source-specific settings;
5. asks for an optional departure seed;
6. asks how much Tessie history to backfill;
7. asks for the dashboard port;
8. offers EcoFlow / Starlink / Tailscale Funnel integrations;
9. installs OS and Python dependencies;
10. creates `/opt/ghost-tesla-ai`;
11. creates `/etc/ghost-tesla-ai` and `/var/lib/ghost-tesla-ai`;
12. creates the Python virtual environment;
13. renders and installs systemd units;
14. initializes the database;
15. enables the collector, dashboard and timers;
16. optionally starts historical backfill;
17. validates the local dashboard/API.

## Installer prompts

### Linux service user

Tesla Intelligence Core runs the application services as a normal Linux user. The installer defaults to the user that launched it.

### Timezone

Departure learning uses local wall-clock time. The installer shows the current timezone and can change the Pi timezone if requested.

### Telemetry source

#### Tessie

Recommended when you want the simplest live source plus historical backfill.

You provide:
- Tessie API token;
- optional VIN.

Leave VIN blank to let the source auto-discover the first vehicle available to the token.

#### TeslaMate MQTT

Use this when TeslaMate is already running.

You provide:
- MQTT host;
- MQTT port;
- TeslaMate car ID;
- optional MQTT username/password;
- optional TLS.

### Departure seed

The installer can accept a typical departure time such as:

```text
06:00
```

This is **not a permanent schedule override**. It is a fading prior while real drive history accumulates. The learned schedule is intended to replace the seed as evidence becomes strong enough.

Leave it blank if you want the system to learn without a starting prior.

### Historical backfill

Tessie installs can pull prior history during bootstrap.

A practical first value is:

```text
30 days
```

Backfill can run in the background. It gives event extraction, schedule learning and model training useful evidence sooner than waiting from zero.

### Dashboard port

Default:

```text
8766
```

Open the dashboard at:

```text
http://PI_ADDRESS:8766
```

### Optional integrations

All optional:
- EcoFlow RIVER 3 telemetry
- Starlink local power telemetry
- Tailscale Funnel + PIN gateway

Core Tesla Intelligence Core functionality does not require them.

## Expected install locations

```text
/opt/ghost-tesla-ai
/etc/ghost-tesla-ai/ghost.env
/etc/ghost-tesla-ai/tessie.token
/var/lib/ghost-tesla-ai
/var/lib/ghost-tesla-ai/models
```

## First validation

After installation:

```bash
ghost-ai status
```

Then check the two main services:

```bash
systemctl status ghost-tesla-ai-web.service --no-pager
systemctl status ghost-tesla-ai-collector.service --no-pager
```

And the learning timers:

```bash
systemctl status ghost-tesla-ai-intelligence.timer --no-pager
systemctl status ghost-tesla-ai-neural.timer --no-pager
```

Open:

```text
http://PI_ADDRESS:8766
```

## What to expect on a new install

A fresh install may initially show low/unknown confidence for:
- commute memory;
- cold-soak evidence;
- learned departure schedule;
- neural predictions;
- charge-rate memory.

That is normal. The project intentionally surfaces thin evidence rather than hiding it.

If Tessie backfill is running:

```bash
tail -f /var/lib/ghost-tesla-ai/bootstrap.log
```

## Useful logs

Dashboard:

```bash
sudo journalctl -u ghost-tesla-ai-web.service -f
```

Collector:

```bash
sudo journalctl -u ghost-tesla-ai-collector.service -f
```

Intelligence cycle:

```bash
sudo journalctl -u ghost-tesla-ai-intelligence.service -f
```

Neural training:

```bash
sudo journalctl -u ghost-tesla-ai-neural.service -f
```

## Updating

From a cloned repository:

```bash
git pull
./update.sh
```

The update path calls the interactive installer again.

Existing runtime history and models live in `/var/lib/ghost-tesla-ai` and are not deleted by normal code updates. Existing config can be preserved when the installer detects it.

## Uninstalling

```bash
./uninstall.sh
```

The uninstaller disables the services and removes the application code. It asks before deleting `/var/lib/ghost-tesla-ai` and `/etc/ghost-tesla-ai`.

## Next steps

- [Configuration](CONFIGURATION.md)
- [Remote access](REMOTE_ACCESS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [FAQ](FAQ.md)
