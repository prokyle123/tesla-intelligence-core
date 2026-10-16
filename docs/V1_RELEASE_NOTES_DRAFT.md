# Tesla Intelligence Core v1.0.0 — Release candidate notes

**Status: DRAFT / UNRELEASED.** The source and GitHub Actions tests on the release branch do **not** constitute a verified Raspberry Pi 5 first-install test. This is not a production-ready release tag.

## What this project does

Tesla Intelligence Core started as a way to understand **overnight winter cold-soak, battery heating, Level 1 AC charging, and whether the car would have enough battery for the next drive**. It has expanded into a local-first, read-only intelligence platform that learns how a specific Tesla behaves over time. All completed drives can contribute useful data, not just regular commutes; unfamiliar destinations and weekend errands are not forced into a home/work assumption.

### v1 release scope

- **Thermal intelligence:** future pack-temperature outlook, outside-weather forecasts (3/6/12 hours), learned parked thermal retention, warm-up and battery heater context, module temperatures and morning-readiness projection.
- **Charging intelligence:** learns slow AC charging and separates fast-charging events from low-power charging evidence. Tracks limits, thermal auxiliary demand and actual input where supported.
- **Vehicle intelligence:** all-trip energy extraction and event history; multiple shadow stages for trip sequence, site context, GPS-confirmed outcomes, feedback, time-only coverage, and trip relationships.
- **Forecast accountability:** records predictions before real events and checks outcomes, with distinct score units and explicit coverage limitations. Forecast Quality v2 and Trip Quality v3.2.1 run **hourly**, independently of model training.
- **Vehicle sensors:** read-only TPMS values, vehicle lock, Sentry Mode, climate fan, charge port and other available state fields. TPMS values are converted from Tesla bar units to PSI; staleness is shown.
- **Machine learning:** classical baselines, neural challenger, governor and held-out checks. Shadow evaluators do **not** automatically alter the serving model.
- **Dashboards:** existing Winter Readiness Home unchanged in layout, separate Forecast Quality, Trip Quality and Vehicle Sensors pages; dark-theme real-time presentation.

### v3.2.1 charging-aware evaluation

A significant drive after a frozen forecast may invalidate a comparison. However, **a charging session already running when that forecast was captured is part of known baseline conditions**, not automatically a disqualifying interruption. A new charge initiated after the capture remains withheld unless reliable evidence establishes the forecast explicitly planned it. This does not prove the charging amount was predicted correctly: departure SOC error remains measurable separately.

Every trip contributes to the observational history even when no suitable prior forecast exists. A skipped or withheld forecast is not counted as a model success or model failure. Time-of-day labels are never proof of the destination.

## One-command setup design

Supported *target* platform: Raspberry Pi 5 with Debian / Raspberry Pi OS 64-bit, Python 3.11+.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/tesla-intelligence-core/main/install.sh)
```

**This command points to the existing published `main` version until v1 is reviewed and merged. Do not install this draft release over a working Ghost Pi.**

A first-time user answers a few guided prompts:
1. Linux service user and local timezone (critical for departure learning).
2. One telemetry source: Tessie API token and optional VIN **or** existing TeslaMate MQTT host, car ID, username, password and TLS.
3. Optional departure seed (fades as historical evidence grows), Tessie historical backfill duration and dashboard port.
4. Optional EcoFlow River, Starlink status or Tailscale access. No optional external hardware is required for the core features.

The installer should then create private data/config directories, install Python dependencies and portable systemd services, initialize database schema, start telemetry collection, schedule model training, forecast-quality and trip-quality verification, and shadow trip learning. Credentials stay on the user's own Pi, not GitHub.

An existing installation should preserve its configuration, credentials, telemetry history, model versions, scores and private trip context. **Do not run the development installer on the current production Pi before upgrade verification.**

## Portable background services

| Unit/timer | Purpose | Intended schedule |
| --- | --- | --- |
| `ghost-tesla-ai-collector.service` | Live telemetry collection | Continuous |
| `ghost-tesla-ai-web.service` | Dashboard and read-only APIs | Continuous |
| `ghost-tesla-ai-intelligence.timer` | Event intelligence | Existing system schedule |
| `ghost-tesla-ai-train.timer` | Baseline training | Existing system schedule |
| `ghost-tesla-ai-neural.timer` | Neural challenger/governor | Existing system schedule |
| `ghost-forecast-quality-v2.timer` | Observed context-sensitive forecast error | Every hour |
| `ghost-trip-quality-v32.timer` | Whole-journey forecast scoring | Every hour |
| `ghost-trip-shadow.timer` | Six existing shadow learners in dependency order | Every 30 minutes |

Private registry, GPS sidecar, quality reports, and model evidence never belong in release assets. Site IDs do not imply user-identifiable routes.

## Data accuracy / transparency

- Winter Readiness **Score** is an operational heuristic, **not** a calibrated model-accuracy percentage.
- Time-only departure labels, GPS-verified route outcomes, and complete candidate journeys are distinct concepts.
- Minute-by-minute rolling windows are correlated. Use independent episodes and completed journeys for model comparison; show sample counts.
- Weather forecasts may use Open-Meteo; no vehicle controls or safety-critical commands are sent.
- Battery energy and Wh/mile should be measured against supported telemetry evidence; do not assume all charging-wall input reaches the pack.
- A missing field, stale observation, or delayed collector is shown as missing/stale rather than silently substituted with a confident prediction.

## Release validation matrix

- [x] Live-source reconciliation and GitHub draft PR staging
- [x] Python syntax and package contract checks in GitHub Actions
- [x] Shadow evaluator unit regressions and six-layer module self-tests
- [x] CI secret-shaped-value guard and host-specific URL cleanup
- [x] Portable service/timer templates committed in release branch
- [ ] Full fresh Raspberry Pi install (user deferred — unavailable hardware)
- [ ] On-Pi upgrade/reboot regression without loss of live services/models/history
- [ ] Extended cold-weather operational validation (requires real winter evidence)
- [ ] Full privacy-reviewed, latest-running-dashboard screenshots
- [ ] Production release tag / user-facing release asset (blocked by above)

**Do not create v1.0.0 release tag before operational acceptance.**
