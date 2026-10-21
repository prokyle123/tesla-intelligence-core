# Feature matrix

## Current GHOST V6.6 development installation

The following capabilities are verified on the running development Pi, **but are not all deployed by the current public v1.0 installer**. See [V2 architecture](GHOST_INTELLIGENCE_V2.md) and [major release gates](V2_RELEASE_GATES.md).

| Capability | Evidence / component | Development status | GitHub fresh-install status |
| --- | --- | --- | --- |
| Guarded local AI insights | Qwen3.5 4B Q4, V6.4.4a claim engine | Running; successful guarded briefing | Portable source/units still needed |
| Voice & alert panel | Browser speech for verified readings; independent rule engine | Running, speech depends on browser permissions | New live HTML and JS not yet reconciled |
| Hourly verified memory | V6.2 snapshot journal | Timer active | Not yet installed by public script |
| Historical charging/thermal comparisons | V5 Tessie context | Running | Optional sidecar package pending |
| Right Now and Next Departure | Separate readiness histories and evidence | Running | Core already present, new UI still needs merge |
| Fast fault/anomaly alerts | Deterministic telemetry evidence gates | Running | Live dashboard source reconciliation needed |
| Watchdog and 0.6B rollback | V6.6 local model service | Endpoint health check passed; full recovery unproven | Portable watchdog installer required |
| Ambient-adjusted thermal learning | V6.5.1 day-heldout experiment | Research only; did not beat simple comparator | Not promoted to production |

**Source terminology:** Tesla-reported charge input isn't an independently measured wall-meter reading. Module-spread medians don't establish a stable cell-temperature distribution. Readiness scores aren't model accuracy. LLM memory retrieval isn't automatic Qwen weight training.

---


This page maps the main Tesla Intelligence Core features to the data or learning layer behind them.

| Area | Feature | What it uses | What it answers |
|---|---|---|---|
| Telemetry | Live SOC / temperatures / charging | Tessie or TeslaMate MQTT | What is happening now? |
| History | Local SQLite telemetry history | Collector snapshots | What has this car been doing? |
| Events | Drive / charge / thermal events | Event intelligence | What meaningful periods occurred? |
| Schedule | Learned departure behavior | Observed drive starts | When does this car normally leave? |
| Thermal | Cold-soak evidence | Thermal event history | How much cold-soak evidence exists? |
| Thermal | Retention behavior | Historical temperature transitions | How does the pack tend to cool / retain heat? |
| Charging | Level 1 / charge-rate memory | Charging events | How does this charging setup behave in practice? |
| Forecast | Future SOC | Classical + neural models | Where is SOC likely to move? |
| Forecast | Future pack temperature | Classical + neural models | How warm/cold is the pack likely to be later? |
| Forecast | Future cabin temperature | Neural multitask output | What cabin-temperature state is expected? |
| Planning | Departure SOC | Schedule + forecast context | What SOC is expected when the car leaves? |
| Planning | Arrival reserve | Learned trip / forecast context | What SOC may remain after the expected drive? |
| Readiness | Winter Readiness Score | Live state + learned evidence + forecasts | Does the next trip look well prepared? |
| Explainability | Readiness Limiters | Score component deductions | What is actually reducing readiness? |
| Audit | Truth Lab | Predictions resolved against later telemetry | Was the forecast right? |
| Model ops | Challenger vs production | Stored model generations | Is a new model better than the serving model? |
| Model ops | Governor / promotion / rollback | Audit and promotion gates | Should a challenger replace production? |
| Integrations | Open-Meteo | Weather API | What environmental context affects the forecast? |
| Integrations | EcoFlow (optional) | EcoFlow telemetry | What external power-system state is available? |
| Integrations | Starlink (optional) | Local Starlink telemetry | What network/power context is available? |
| Remote | Tailscale (optional) | Tailnet | How can the dashboard be reached privately? |
| Remote | PIN Funnel gateway (optional) | Tailscale Funnel + local gateway | How can public HTTPS be gated? |

## v1 release-candidate features

| Area | Feature | Evidence | Limitation |
| --- | --- | --- | --- |
| Forecast Quality | v2 evaluator with activity context | Resolved frozen windows and independent origin episodes | Overlapping windows aren't independent trips |
| Trip Quality | v3.2.1 charge-aware whole-journey scorer | Candidate journeys, observed coverage, optional GPS-verified endpoints | Time-of-day is not destination truth |
| All-trip learning | Six shadow trip stages and every-drive reporting | Weekend, unfamiliar and multi-leg drives | Requires sufficient observed history |
| Vehicle sensors | TPMS in PSI, Sentry, lock, charge port, climate fan | Existing Tessie state payload | Values can be stale while parked |
| Outdoor weather | 3h, 6h, 12h outlook | Open-Meteo hourly forecast | This is outside air, not actual pack temperature |
| Operations | Periodic local quality and trip jobs | Portable systemd timers | Shadow evaluations cannot promote live models |

## Technology stack

- **Python 3.11+** — collection, event intelligence, forecasting, API and control plane
- **PyTorch** — GRU temporal neural engine
- **scikit-learn** — classical baseline models
- **Flask** — local API and dashboard serving
- **HTML / CSS / JavaScript** — interactive dashboard UI
- **SQLite** — telemetry, events, audit and model-state persistence
- **Bash** — installation / update / uninstall tooling
- **systemd** — services and scheduled intelligence/training jobs
- **MQTT** — TeslaMate ingestion path
- **GitHub Actions / YAML** — repository smoke checks
