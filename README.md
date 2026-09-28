# GHOST Tesla AI

**Local-first Tesla winter-readiness, thermal, charging, trip-pattern and energy learning for Raspberry Pi.**

![Version](https://img.shields.io/badge/version-0.8.27.6-40e0d0)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-64--bit-c51a4a)
![License](https://img.shields.io/badge/license-MIT-green)

GHOST turns Tesla telemetry into a continuously learning local model of **your car**: how the battery warms and cools, how fast it charges, when trips usually happen, how much SOC they use, and what condition the car is likely to be in when you leave.

It was built first as a winter-readiness dashboard and grew into a local Tesla telemetry + machine-learning lab.

> **Read-only project:** GHOST observes telemetry and builds predictions. It does not send driving, climate, charging, locking, or other control commands to the vehicle.

![GHOST dashboard](docs/images/dashboard-overview.png)

## What it does

- **Winter Readiness Score (0-100)** with human-readable **Winter Readiness Limiters** explaining every active point deduction.
- **Battery thermal intelligence** using pack/module temperatures, outside air, thermal margin, cooling/warming trend and cold-soak history.
- **Future pack-temperature forecasts** including learned 1-hour / 3-hour outlooks and weather-linked cold conditions.
- **Learned departure schedule** from real drive history instead of a permanently hard-coded commute time.
- **Routine vs random trip handling** so occasional drives do not destroy the normal schedule model.
- **Next-trip probability + confidence** separate from overall schedule quality.
- **Departure SOC, projected arrival SOC, pack-at-departure and warm-up recommendations.**
- **Level-1 / charging memory** for real charge-rate and overnight behavior.
- **Cabin HVAC + preconditioning observation** and battery-heater state.
- **PyTorch GRU temporal model** with shadow/challenger training, promotion gates and rollback logic.
- **Classical ML models** for SOC, cabin and pack-temperature prediction.
- **Prediction auditing / Truth Lab** to compare forecasts against what actually happened.
- **Automatic telemetry event extraction** for drives, charging, cold soak and thermal events.
- **Tessie API or TeslaMate MQTT** as telemetry sources.
- **Historical Tessie backfill** so a fresh install can begin learning from prior data immediately.
- **Open-Meteo weather context** with no weather API key required.
- **Optional EcoFlow RIVER 3 status** in the operations header.
- **Optional Starlink local power telemetry.**
- **Optional Tailscale Funnel + local PIN gateway** for remote HTTPS access without exposing the raw dashboard directly.
- **SQLite local history + local model files.**

## Quick install

Recommended target: **Raspberry Pi 5, 64-bit Raspberry Pi OS or Debian**.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/ghost-tesla-ai/main/install.sh)
```

The installer is interactive. It asks for only what it needs, including:

- Linux user to run GHOST
- local timezone
- Tessie **or** TeslaMate MQTT
- Tessie token and optional VIN, if using Tessie
- optional initial departure-time seed
- amount of history to backfill
- optional EcoFlow RIVER 3 integration
- optional Starlink telemetry support
- optional PIN-protected Tailscale Funnel

Secrets are written to the Pi, **not** committed to the repository.

See [Installation](docs/INSTALL.md) for the full process.

## Dashboard

The main screen is deliberately centered on one question:

> **If I leave when GHOST thinks I am going to leave, what condition will the battery and car be in?**

The top Winter Readiness card combines live pack state, weather, expected departure, arrival reserve and learned evidence. If the score is below 100, **Winter Readiness Limiters** explain the reason and exact point hit.

### Learned departure planning

![Learned departure planning](docs/images/departure-learning.png)

A configured departure time is only a **fading prior**. Once enough real drives exist, observed behavior takes over. Random trips remain useful training data but are down-weighted relative to repeated routine departures.

## Data flow

```text
Tessie API / TeslaMate MQTT
          |
          v
   telemetry collector
          |
          v
      SQLite history
       /     |      \
      /      |       \
 events   classical ML   PyTorch GRU
      \      |       /
       \     |      /
        readiness + forecasts
                |
                v
        Flask dashboard :8766
                |
        optional PIN gateway :8777
                |
        optional Tailscale Funnel
```

More detail: [Architecture](docs/ARCHITECTURE.md).

## Where data lives

By default:

- Code: `/opt/ghost-tesla-ai`
- Config: `/etc/ghost-tesla-ai/ghost.env`
- Tessie token: `/etc/ghost-tesla-ai/tessie.token`
- SQLite / learned state: `/var/lib/ghost-tesla-ai`
- Models: `/var/lib/ghost-tesla-ai/models`

The repository intentionally ignores databases, tokens, environment files, trained model artifacts and logs.

## Useful commands

```bash
# Overall status
ghost-ai status

# Run an intelligence cycle now
ghost-ai intelligence

# Follow the dashboard log
sudo journalctl -u ghost-tesla-ai-web.service -f

# Follow telemetry collection
sudo journalctl -u ghost-tesla-ai-collector.service -f

# Dashboard
http://PI_ADDRESS:8766
```

## Hardware / performance

A Pi 5 is recommended because neural training is CPU-intensive. The live dashboard and telemetry collector are light; GRU training is the expensive part and runs separately so the dashboard can remain responsive.

The code is not intentionally locked to one Tesla model, but development/testing has primarily been around Model 3 telemetry. Different vehicles and telemetry providers may expose different fields, so community testing is welcome.

## Security and privacy

GHOST can contain extremely personal vehicle history. Before exposing it remotely, read [Security](SECURITY.md) and [Remote access](docs/REMOTE_ACCESS.md).

Important defaults:

- telemetry/history stays local on the Pi unless your telemetry provider itself is cloud-based;
- Tessie credentials are stored outside the repository;
- the optional public Funnel is designed to terminate at GHOST's PIN gateway on `127.0.0.1:8777`;
- direct LAN/Tailscale access can remain private on port `8766`.

## Project status

This is an experimental enthusiast project, not a Tesla product and not a safety system. Predictions are estimates and should not be treated as guarantees about battery temperature, range, charging completion or vehicle operation.

## Documentation

- [Install](docs/INSTALL.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Remote access](docs/REMOTE_ACCESS.md)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).

---

GHOST Tesla AI is not affiliated with or endorsed by Tesla, Tessie, EcoFlow, Starlink, Tailscale, or Open-Meteo. Product and service names belong to their respective owners.
