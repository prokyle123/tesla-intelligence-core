# Configuration

Primary configuration lives at:

```text
/etc/ghost-tesla-ai/ghost.env
```

Tessie tokens are stored separately at:

```text
/etc/ghost-tesla-ai/tessie.token
```

Restart services after changing configuration:

```bash
sudo systemctl restart ghost-tesla-ai-collector.service ghost-tesla-ai-web.service
```

## Common settings

| Setting | Purpose | Default |
|---|---|---|
| `GHOST_AI_PORT` | Dashboard/API port | `8766` |
| `SOURCE_MODE` | `tessie`, `mqtt`, or `auto` | installer selection |
| `TESSIE_VIN` | Optional VIN; blank auto-discovers | blank |
| `TESSIE_POLL_SECONDS` | Tessie live polling interval | `60` |
| `EXPECTED_DEPARTURE` | Optional fading departure prior | blank |
| `DEPARTURE_LEARNING_ENABLED` | Learn departure patterns | `true` |
| `DEPARTURE_LOOKBACK_DAYS` | Schedule-learning history window | `90` |
| `READINESS_TARGET_PACK_F` | Preferred departure pack temp | `50` |
| `READINESS_MIN_ARRIVAL_SOC` | Arrival reserve policy | `20` |
| `EVENT_LOOKBACK_DAYS` | Event learning history | `60` |
| `NEURAL_V4_ENABLED` | PyTorch GRU engine | `true` |
| `NEURAL_GOVERNOR_ENABLED` | Neural promotion/rollback governor | `true` |
| `WEATHER_ENABLED` | Open-Meteo weather context | `true` |
| `ECOFLOW_RIVER3_SN` | Optional EcoFlow device serial | blank |

Many additional neural/governor tuning values exist in `ghost_tesla_ai/config.py`. Defaults are intentionally conservative for a Pi 5.

## Data directories

- DB: `/var/lib/ghost-tesla-ai/ghost_ai.sqlite3`
- model artifacts: `/var/lib/ghost-tesla-ai/models`
- neural logs/state: `/var/lib/ghost-tesla-ai`
- optional EcoFlow app credentials: `/var/lib/ghost-tesla-ai/ecoflow_app.json`
- optional Funnel PIN hash/session secret: `/var/lib/ghost-tesla-ai/funnel_pin.json`
