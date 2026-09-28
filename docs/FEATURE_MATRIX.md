# Feature matrix

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
