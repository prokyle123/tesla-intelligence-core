# Feature matrix

## Latest development Pi (guarded GHOST V6.6)

These are **observed on the running developer Pi** and are **not all included in the public v1.0 installer**. Complete V2 packaging is tracked in [draft pull request #4](https://github.com/prokyle123/tesla-intelligence-core/pull/4).

| Feature | How it works | Public installer status |
| --- | --- | --- |
| AI Insight | Local Qwen3.5 4B with verified sensor evidence and claim-aware fallback | Not yet packaged for fresh installs |
| Verified voice/alerts | Browser voice controls, hourly observations, qualified rule alerts | Latest live dashboard source pending reconciliation |
| Historical intelligence | V5 charging/thermal baselines, V6.2 memory | Sidecar/units not yet integrated |
| Battery and charging | Direct heater, module spread, charging input and derived power path | Core available; newest UI pending |
| Separate readiness modes | Right Now / Next Departure, limiters and recorded history | Core present, newest UI pending |
| Weather and pack outlook | Open-Meteo plus thermal projections with ranges still calibrating | Existing core; current UI pending |
| Guarded 4B watchdog | Health probe, 0.6B rollback configuration | Portable recovery installer not yet released |
| Ambient thermal holdout | V6.5.1 research model worse than simple baseline | Not promoted |

**Important:** Vehicle charging input is Tesla-reported, not a wall-meter reading. Model weight training is independent of Qwen narration. Historical medians do not prove stability or fault-free operation.

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
