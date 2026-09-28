# Installation

## Recommended platform

- Raspberry Pi 5 recommended
- 64-bit Raspberry Pi OS or Debian
- Internet access during installation
- Python 3.11+
- Tessie account/token **or** an existing TeslaMate MQTT broker

## Interactive one-line install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/ghost-tesla-ai/main/install.sh)
```

The script clones the repository to a temporary directory, asks for configuration, installs the runtime under `/opt/ghost-tesla-ai`, creates systemd services, and starts the dashboard/collector.

## Installer prompts

### Linux service user
GHOST runs as a normal Linux user, not root. The installer defaults to the user running the installer.

### Timezone
Departure learning uses local wall-clock time. Make sure the Pi timezone matches the car/user's intended schedule timezone.

### Telemetry source
**Tessie:** easiest route to live telemetry + historical backfill.

**TeslaMate MQTT:** fully local source when TeslaMate is already running. You provide MQTT host/port/car ID and optional authentication.

### Departure seed
Optional. This is **not a permanent schedule override**. It acts only as a fading prior while GHOST builds enough real drive history.

### Historical backfill
Tessie users can import historical states immediately. Thirty days is a reasonable starting point. Backfill runs in the background and can populate enough data for the learning systems much faster than waiting from zero.

### Optional integrations
EcoFlow, Starlink and Tailscale Funnel are all optional. Core GHOST does not require them.

## After installation

Open:

```text
http://PI_ADDRESS:8766
```

Check services:

```bash
ghost-ai status
systemctl status ghost-tesla-ai-web.service
systemctl status ghost-tesla-ai-collector.service
systemctl status ghost-tesla-ai-intelligence.timer
systemctl status ghost-tesla-ai-neural.timer
```

## Updating

From a cloned repository:

```bash
git pull
./update.sh
```

Runtime history, models and secrets are kept outside the code directory and are preserved.
