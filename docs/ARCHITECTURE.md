# Architecture

GHOST is intentionally split into independent pieces so expensive learning jobs do not block the live dashboard.

## Collector

`ghost-tesla-ai-collector.service` normalizes Tessie or TeslaMate telemetry into SQLite. The collector avoids inserting duplicate cached Tessie samples.

## Event intelligence

A 15-minute systemd timer extracts higher-level events from telemetry: drives, charging periods, thermal retention/cold-soak evidence and related context.

## Classical models

Scikit-learn models provide baseline predictions for SOC, cabin and pack temperatures. Model generations are stored separately instead of blindly replacing the previous model.

## Neural engine

The PyTorch GRU learns temporal behavior from sequences rather than single snapshots. Training runs separately from inference. A governor compares challenger behavior against holdout/truth evidence before promotion and can roll back a regressing neural generation.

## Departure learning

Departure timing is learned from real drive events. A configured `EXPECTED_DEPARTURE` is a fading prior only. Repeated first-drive patterns receive stronger evidence than isolated secondary/random trips.

## Winter readiness

The readiness layer combines observed and predicted state into a human-readable score and limiter list. The score is operational readiness, not model accuracy.

## Dashboard/API

Flask serves the dashboard and versioned APIs on port `8766`. Optional remote public access proxies through the PIN gateway on port `8777` before Tailscale Funnel.
