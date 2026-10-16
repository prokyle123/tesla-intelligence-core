# Tesla Intelligence Core v1.0 — release staging

> **Status: NOT RELEASED.** This document tracks the work needed before publishing a major version. The running Raspberry Pi may have newer source and manually installed services that are **not** part of the public repository.

## Product objective

A **local-first, read-only vehicle intelligence system** for Tesla owners. Its original focus is overnight winter cold soak, slow AC charging, battery heating, and next-departure readiness. It has expanded to learn energy and charging behavior from **all trips**, including errands, weekends, unusual routes, fast charging, parking and multi-stop days — not just commutes.

## Observed on the development Pi (October 2026)

These components have been exercised on the development system. **Do not claim they are in the public installer until their sources/services are audited and integrated.**

- Live telemetry via Tessie and optional TeslaMate MQTT; preserved original JSON and curated typed fields; Sentry Mode, pack, charging and thermal evidence.
- Winter readiness board, pack thermal outlook, weather tiles at 3/6/12 hours, battery heater and charging power context, score history, neural engine, Truth Lab and governor safeguards.
- DC fast-charge vs. Level 1 classification fix and charging-rate safeguards.
- Multi-trip schedule, location context and shadow trip verification / feedback / coverage layers.
- Forecast Quality v1/v2 shadow scoring: clean parked predictions, activity transitions, independent origin-episode proxies and seven-day snapshots.
- Trip Quality v3/v3.1/v3.2 shadow scoring: completed drive events, multi-leg reconstruction, intervening activity qualification and GPS-verified sidecar comparisons.
- Vehicle Sensors view: four TPMS readings converted from bar to PSI, Sentry status, lock / charge port / climate fan states.
- Hourly evaluators and web endpoints. The **current on-Pi units** must be converted to portable systemd templates; do not hardcode a particular username or /home directory.

## Must pass before the major release tag

1. **Source reconciliation:** compare public `main` to the latest live code using a source-only export; audit hashes and diffs; intentionally merge changes rather than overwriting newer public fixes.
2. **Secrets review:** no VIN, GPS traces, tokens, MQTT passwords, private addresses or runtime databases, logs, model artifacts, PINs, or EcoFlow credentials in the Git commit or image assets.
3. **One-step first install:** one command, clear interactive setup (Tessie token OR TeslaMate MQTT, timezone, optional departure hint, optional integrations); safe token storage outside the repo; bootstrap data and automatic scheduled services.
4. **Safe upgrades:** detect and reuse existing configuration without demanding credentials again; preserve DB, models, reports and learned evidence; backup code; never delete running-only features when switching to the public installer.
5. **Service orchestration:** versioned web, collector, training, neural governor, trip intelligence, Forecast Quality and Trip Quality evaluator units/timers all installed automatically. No duplicate retired timers.
6. **Model accountability:** maintain shadow vs production separation. Handle planned overnight charging differently from unexpected intervening trips/charging; neither silently exclude legitimate forecasts nor overstate evidence.
7. **Test matrix:** clean Raspberry Pi OS / Debian 64-bit installation; reinstall over v0.8.x; retry interrupted install; run restart/reboot tests, telemetry unavailable tests, HTTP route smoke checks, and unit timer checks.
8. **UI & docs:** preserve current Home dashboard. Update README, changelog, compatibility, feature matrix and install screenshots from the **real installed** UI; inspect screenshot for sensitive data before publishing.
9. **Release candidate:** tag only after a fresh-machine install and end-to-end validation, not merely a Python syntax check. Publish a release with supported platforms, limitations and migration instructions.

## Source snapshot handoff

A private, source-only export from `/opt/ghost-tesla-ai` and the installed evaluation scripts is needed. Do **not** upload the export itself to the public repo: verify that it contains no embedded secrets or machine-specific locations, then move vetted source into appropriate tracked package directories. The tool-created snapshot intentionally excludes telemetry history and credentials.

## Non-goals

- Sending car-control commands, charging or climate commands, or disabling Tesla safety systems.
- Automatically promoting neural challengers based on a few favorable commutes.
- Claiming verified range, cold-weather performance or “AI accuracy” from tiny or overlapping samples.
- Exposing vehicle location from exported reports or public screenshots.

## Release candidate approval

This staging branch is for development/review only. It is **not** a v1.0 installable distribution until the above items are checked off.
