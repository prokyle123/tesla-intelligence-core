# October 2026 â€” GHOST development snapshot

This document describes the **source actually exported from the running GHOST Raspberry Pi**, not an imagined future release. Exported: 20261011-183903.

## Winter readiness and departure scheduling

- Existing **NEXT DEPARTURE** readiness score combines thermal forecast, projected arrival SOC, predicted departure charge, and evidence confidence. The score is operational guidance, **not model accuracy**.
- Learned departure patterns can roll forward to the next supported departure after an earlier candidate expires (observed from an evening candidate to the next morning).
- The vehicle and battery are **not remotely controlled** by the predictor.
- Installed in exported source: one main gauge switches RIGHT NOW / NEXT DEPARTURE, with separate 12-hour recorded score histories.
- Winter Score history adapter is present; the source should be checked for whether the live sampler timer is enabled on deployment.

## Trip learning / accountability

- All six shadow modules are included in this source snapshot; they operate separately from production scoring.
- Layer v1: trip sequence / observed chains.
- Layer v2: anonymous stable site context; nearby sites are not automatically merged.
- Layer v3.2: prospective route predictions and complete-drive accountability.
- Layer v4: verified-trip feedback, advisory only (no automatic model correction).
- Layer v5: prospective time-only coverage independent of GPS route certainty.
- Layer v6: deduplicated comparison of location-aware and time-only evidence.

These layers deliberately do **not** auto-promote their conclusions into production readiness or neural forecasting. They remain evaluated independently until enough verified trips exist.

## Neural training

The PyTorch GRU is a challenger trained against a baseline on held-out historical days. A new training generation is not automatically a production promotion. Real-world prediction accuracy remains the deciding factor.

## Charging-safety correction

An October 9 fast-charge audit found that an observed ~230 kW DC session (34.5 kWh added in ~20 minutes) had been assigned **0 kW mean charging power** by the old event classification. Its SOC gain could therefore slip into learned low-power charging rates.

- `ghost_tesla_ai/event_engine.py` now contains the `GHOST-L1-FASTCHARGE-GUARD-V1` correction.
- Charge classification accounts for alternate power readings, added energy and impossible SOC/hour rates.
- Only suitable low-power sessions feed the learned Level 1 SOC/hour median; high-power events remain in the historical record.
- At verification, the estimated Level 1 median changed from **1.385** to **1.374 SOC percentage points/hour** (55 to 53 accepted samples, based on the installation audit). This is a historical diagnostic, **not a current live forecast**.

## Safety / privacy / publishing scope

This GitHub source sync only includes `ghost_tesla_ai/**/*.py` and `web/templates/index.html` from the Pi, plus public documentation. It **does not** upload vehicle telemetry, charging logs, SQLite files, trained `.pt`/`.joblib` weights, individual location registries, Tessie credentials, EcoFlow tokens, PIN data, or private `.env` files. User-specific Tailnet hostnames are replaced in the exported code only (the Pi remains unchanged).

Live-service systemd installation and scheduled timers are separate from this repository source snapshot; run-time service units were **not** copied from `/etc/systemd/system` because they may contain private machine-specific paths or settings.

## Screenshot note

The repository's existing screenshots remain available. This sync deliberately does not pass off a conceptual design rendering as a live dashboard screenshot. New current-state images can be added after capturing the installed UI with sensitive data excluded.