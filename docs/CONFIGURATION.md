# Configuration

Tesla Intelligence Core keeps runtime configuration outside the repository.

> Internal paths and variables retain the original `ghost` naming for compatibility.

Primary configuration:

```text
/etc/ghost-tesla-ai/ghost.env
```

Tessie token:

```text
/etc/ghost-tesla-ai/tessie.token
```

Runtime data:

```text
/var/lib/ghost-tesla-ai
```

## Applying changes

After editing configuration:

```bash
sudo systemctl restart ghost-tesla-ai-collector.service ghost-tesla-ai-web.service
```

For settings that affect learning/model jobs, you can also restart the related timers/services or simply let the next scheduled cycle run.

## Common settings

| Setting | Purpose | Default / installer value |
|---|---|---|
| `GHOST_AI_HOST` | Flask listen address | `0.0.0.0` |
| `GHOST_AI_PORT` | Dashboard/API port | `8766` |
| `GHOST_AI_DATA_DIR` | Runtime data root | `/var/lib/ghost-tesla-ai` |
| `SOURCE_MODE` | `tessie`, `mqtt`, or `auto` | installer selection |
| `TESSIE_BASE_URL` | Tessie API base | `https://api.tessie.com` |
| `TESSIE_VIN` | Optional VIN; blank can auto-discover | blank |
| `TESSIE_POLL_SECONDS` | Tessie live polling interval | `60` |
| `MQTT_HOST` | TeslaMate MQTT broker | installer selection |
| `MQTT_PORT` | MQTT port | `1883` |
| `TESLAMATE_CAR_ID` | TeslaMate vehicle ID | `1` |
| `SNAPSHOT_SECONDS` | Snapshot cadence | `60` |
| `EXPECTED_DEPARTURE` | Optional fading departure prior | blank |
| `DEPARTURE_LEARNING_ENABLED` | Learn departure behavior | `true` |
| `DEPARTURE_LOOKBACK_DAYS` | Departure learning history | `90` |
| `DEPARTURE_PRIOR_STRENGTH` | Initial prior influence | `0.55` |
| `DEPARTURE_PRIOR_FADE_DAYS` | Prior fade period | `20` |
| `READINESS_TARGET_PACK_F` | Preferred departure pack temp | `50` |
| `READINESS_MIN_ARRIVAL_SOC` | Arrival SOC reserve target | `20` |
| `EVENT_LOOKBACK_DAYS` | Event-learning history | `60` |
| `EVENT_MAX_GAP_MINUTES` | Event continuity gap | `20` |
| `COLD_SOAK_THRESHOLD_C` | Cold-soak threshold | `10.0` |
| `NEURAL_V4_ENABLED` | PyTorch GRU engine | `true` |
| `NEURAL_CHALLENGER` | Train challenger generations | `true` |
| `NEURAL_GOVERNOR_ENABLED` | Promotion/governor layer | `true` |
| `NEURAL_GOVERNOR_AUTO_PROMOTE` | Permit auto-promotion | `true` |
| `WEATHER_ENABLED` | Weather context | `true` |
| `WEATHER_CACHE_MINUTES` | Weather cache duration | `20` |
| `ECOFLOW_RIVER3_SN` | Optional EcoFlow serial | blank |

Additional tuning values exist in `ghost_tesla_ai/config.py`. Defaults are intended to be conservative enough for Pi-class hardware.

## Tessie

Token file:

```text
/etc/ghost-tesla-ai/tessie.token
```

Permissions are set so the configured service user can read it while keeping it outside the source tree.

Do not put the token in README examples, GitHub issues, screenshots, or committed environment files.

## TeslaMate MQTT

Common variables:

```text
MQTT_HOST=
MQTT_PORT=1883
MQTT_USER=
MQTT_PASSWORD=
MQTT_TLS=false
TESLAMATE_CAR_ID=1
```

The broker must be reachable from the machine running Tesla Intelligence Core.

## Departure learning

A value such as:

```text
EXPECTED_DEPARTURE=06:00
```

is only a starting prior.

The learner uses real drive starts and gradually reduces reliance on the configured seed. Repeated first-departure patterns gain more weight than isolated secondary/random drives.

To disable schedule learning:

```text
DEPARTURE_LEARNING_ENABLED=false
```

## Readiness policy

These are policy-style targets rather than physical guarantees:

```text
READINESS_TARGET_PACK_F=50.0
READINESS_MIN_ARRIVAL_SOC=20.0
```

Changing them changes how readiness is evaluated.

## Data directories

Database:

```text
/var/lib/ghost-tesla-ai/ghost_ai.sqlite3
```

Model artifacts:

```text
/var/lib/ghost-tesla-ai/models
```

Optional EcoFlow app credentials:

```text
/var/lib/ghost-tesla-ai/ecoflow_app.json
```

Optional Funnel PIN hash/session secret:

```text
/var/lib/ghost-tesla-ai/funnel_pin.json
```

## Backups

For a simple manual runtime backup:

```bash
sudo systemctl stop ghost-tesla-ai-collector.service ghost-tesla-ai-web.service
sudo tar -czf tesla-intelligence-core-runtime-backup.tgz \
  /etc/ghost-tesla-ai \
  /var/lib/ghost-tesla-ai
sudo systemctl start ghost-tesla-ai-collector.service ghost-tesla-ai-web.service
```

That archive can contain highly sensitive telemetry and credentials. Protect it accordingly.
