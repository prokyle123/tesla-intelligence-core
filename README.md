<div align="center">

# Tesla Intelligence Core

### Local AI explanations, verified winter readiness, neural forecasts, and Level 1 charging intelligence.

**Tesla telemetry → local history → learned forecasts → verified evidence → optional Qwen3.5 4B insight → voice alerts**

**Built for cold-soaked batteries, slow home charging, everyday vehicle use, and people who want evidence instead of guesses.**

[![Release](https://img.shields.io/github/v/release/prokyle123/tesla-intelligence-core?display_name=tag&sort=semver)](https://github.com/prokyle123/tesla-intelligence-core/releases)
[![Smoke](https://github.com/prokyle123/tesla-intelligence-core/actions/workflows/smoke.yml/badge.svg)](https://github.com/prokyle123/tesla-intelligence-core/actions/workflows/smoke.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-5%20recommended-c51a4a)
![Read only](https://img.shields.io/badge/Vehicle%20control-read--only-2ea44f)

**Core stack**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-GRU-EE4C2C?logo=pytorch&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-baseline%20ML-F7931E?logo=scikitlearn&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-dashboard-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local%20history-003B57?logo=sqlite&logoColor=white)
![Web UI](https://img.shields.io/badge/Web%20UI-HTML%20%2F%20CSS%20%2F%20JS-E34F26?logo=html5&logoColor=white)
![Bash](https://img.shields.io/badge/Bash-installer%20%2B%20ops-4EAA25?logo=gnubash&logoColor=white)
![systemd](https://img.shields.io/badge/systemd-services%20%2B%20timers-5B5B5B)

**New in the October V6.6 development system · V2 release integration**

![Local LLM](https://img.shields.io/badge/local%20LLM-Qwen3.5%204B-4f46e5)
![llama.cpp](https://img.shields.io/badge/inference-llama.cpp-555555)
![C++](https://img.shields.io/badge/C%2B%2B-llama.cpp%20runtime-00599C?logo=cplusplus&logoColor=white)
![Voice alerts](https://img.shields.io/badge/voice-Browser%20Speech%20API-14b8a6)
![Guarded AI](https://img.shields.io/badge/narration-evidence%20guarded-22c55e)
![Historical memory](https://img.shields.io/badge/memory-local%20snapshots-0ea5e9)
![Watchdog](https://img.shields.io/badge/model-watchdog%20%2B%20fallback-f97316)

**Built around real EV constraints**

![Winter](https://img.shields.io/badge/cold--weather-ready-1f6feb)
![Level 1](https://img.shields.io/badge/Level%201-slow%20charging-f59e0b)
![Tessie](https://img.shields.io/badge/source-Tessie-6f42c1)
![TeslaMate](https://img.shields.io/badge/source-TeslaMate-0ea5e9)
![Local first](https://img.shields.io/badge/data-local--first-2ea44f)
![Predictive](https://img.shields.io/badge/focus-predictive%20analytics-8b5cf6)
![Android companion](https://img.shields.io/badge/Android-companion%20v0.9.5-3DDC84?logo=android&logoColor=white)
![Tesla browser](https://img.shields.io/badge/in--car%20browser-PIN%20Funnel-43D8FF)

**[V2 preview release](https://github.com/prokyle123/tesla-intelligence-core/releases/tag/v2.0.0-preview.1) · [Latest dashboard](docs/images/ghost-v2-dashboard-live.webp) · [New AI + voice](#new-v66-intelligence-and-voice-features) · [Full features](docs/FEATURE_MATRIX.md) · [Changelog](CHANGELOG.md) · [Install v1](#quick-start) · [Docs](#documentation)**

⭐ **If this project is useful to you, star the repository.** It is the simplest way to help other Tesla / EV tinkerers discover it.

</div>

Tesla Intelligence Core is a **self-hosted Tesla battery analytics, predictive telemetry and machine-learning platform for Raspberry Pi** built around one practical question:

> **When I leave next, what condition will the car and battery actually be in?**

Because **80% SOC is not the whole answer**.

A car sitting at 80% on a mild afternoon is not the same situation as a car sitting at 80% after hours of cold soak before a long winter commute. If home charging is slow, every hour of available charging matters. If the drive is long, departure SOC is only half the story — the reserve expected at the other end matters too.

Tesla Intelligence Core watches live telemetry, builds a local history, learns recurring behavior, extracts trips/charging/thermal events, and trains numerical and neural prediction models. On the current development Pi, a separate **local Qwen3.5 4B model** explains selected verified readings, historical comparisons and readiness results in natural language, while voice alerts and rule-based warnings stay independent of slower model inference.

It started as a winter-readiness project and grew into a broader local vehicle-intelligence platform.

> [!IMPORTANT]
> **Read-only by design.** Tesla Intelligence Core observes telemetry and builds predictions. It does **not** send driving, climate, charging, locking, or other control commands to the vehicle.

### Built for real-world EV constraints

Tesla Intelligence Core is especially useful when **time, temperature and charging speed all matter at once**.

| Situation | What the system adds |
|---|---|
| **❄️ Long winter commute** | Learns typical trip behavior, projects departure conditions and estimates **arrival SOC reserve** instead of stopping at the current battery percentage. |
| **🔌 Level 1 / slow home charging** | Learns the car's charging behavior, tracks Tesla-reported input power (not an independent wall meter) and estimates whether charge is on pace for the next departure. |
| **🥶 Outdoor / cold-soaked car** | Tracks pack and module temperatures, cold-soak evidence, thermal retention, governed 1h / 3h / 6h pack forecasts, and learned preconditioning duration. |
| **🕒 Departure time changes** | Learns recurring drive starts from history and keeps **schedule confidence** separate from **next-trip confidence**, so a random trip does not have to redefine the routine. |
| **⚡ Charging + thermal load together** | Shows charging power alongside derived pack / non-pack power so it is easier to understand where limited input power is going. |
| **📉 Tight energy margin** | Combines departure SOC, projected trip use, expected arrival reserve and thermal context instead of relying on one live SOC number. |
| **🧠 You want evidence, not magic** | Exposes prediction ranges, Truth Lab results, model generations, challenger/production state and readiness limiters instead of hiding everything behind a generic “AI” score. |

#### The kind of questions it is built to answer

- **Will slow overnight charging actually get me where I want to be by departure?**
- **Will the pack still be cold when I leave?**
- **How much SOC am I likely to have after the drive, not just before it?**
- **Is today's thermal behavior normal for this car?**
- **Is the current forecast based on strong history or thin evidence?**
- **Did previous predictions turn out to be right?**
- **Is the model improving enough to replace the current production model?**

> **For people who depend on the car every day, the useful question is not “what does the telemetry say right now?” It is “what is this car likely to look like when I actually need it?”**


<p align="center">
  <a href="docs/images/ghost-v2-dashboard-live.webp">
    <img src="docs/images/ghost-v2-dashboard-live.webp" alt="Actual current GHOST V6.6 dashboard showing AI Insight, Voice Alerts, Right Now Winter Readiness, battery state, future pack and outdoor weather, and thermal power flow" width="98%">
  </a>
</p>
<p align="center"><sub><b>Actual GHOST V6.6 running dashboard • October 2026</b> — local AI commentary, verified readings, voice alerts, winter readiness, forecast context and electrical power analysis. This is a genuine development-system screenshot, not generated artwork. Displayed values are a point-in-time example. <b>Public v1 installer does not yet reproduce every V6.6 feature shown.</b></sub></p>

---

## New V6.6 intelligence and voice features

The current development Raspberry Pi now runs a **guarded Qwen3.5 4B local-language-model explanation engine** alongside GHOST's existing independently trained numerical and PyTorch neural predictors. The 4B model adds commentary—not vehicle control, autonomous model-weight training, or replacements for verified measurements.

| New area | What is running on the development Pi |
| --- | --- |
| **Local 4B AI Insight** | Cached, asynchronous briefings in natural language about charging, pack temperature, readiness and qualified historical patterns |
| **Verified-data grounding** | Numerical and relationship checks reject invented measurements, unsupported trends, false module-spread comparisons and unverified fault-free assertions |
| **Trusted fallback** | A rejected or unavailable 4B explanation is replaced by deterministic verified text; the readiness and rule-alert engines remain independent |
| **V5 Tessie deep signals** | Separate battery heater, HVAC, Tesla conditioning, vehicle-reported charge input, module spread and historical baselines |
| **V6.2 learning memory** | Hourly local verified observations and retrieved context—not language-model self-training or automatic weight updates |
| **Voice and alerts** | Read verified status aloud, optional AI analysis, scheduled top-of-hour speech and rule-based anomaly announcements in compatible browsers |
| **Winter readiness** | Distinct **RIGHT NOW** versus **NEXT DEPARTURE** scores, recorded trend and evidence-based limiter descriptions |
| **Weather and battery outlook** | Open-Meteo context, future pack estimates, cabin thermal and power-flow panels; unvalidated forecast uncertainty bands remain blank |
| **Reliability** | 4B watchdog health check, cached commentary and retained 0.6B recovery path; unattended failure/reboot testing is still needed |
| **Thermal research** | V6.5/V6.5.1 day-separated passive thermal studies remain experimental; the ambient model was **not promoted** after a weaker holdout score |

> [!CAUTION]
> **GitHub installation status:** These V6.6 features are verified on the developer Pi, but the public **v1.0 installer does not yet install the entire V6.6 system**. The V2 packaging, portable model setup, migration/rollback and clean-install validation are still in progress. [Read the full development-to-release notes](docs/V2_RELEASE_NOTES_DRAFT.md) and [V2 release gates](docs/V2_RELEASE_GATES.md). Do not overwrite an existing updated installation with the old v1 installer.

### What the AI actually learns

GHOST's separate trained predictors learn numerical behavior from qualifying telemetry and outcomes. The local language model **retrieves verified evidence and memory snapshots to explain them**; that retrieval does not continuously fine-tune its Qwen weights. Both systems can be useful without confusing a conversational explanation with a measured forecast or diagnostic proof.

For a technical breakdown of the independent systems, see [GHOST Intelligence V2 architecture](docs/GHOST_INTELLIGENCE_V2.md) and the [feature matrix](docs/FEATURE_MATRIX.md).

**V2 source release status (October 21):** the current running Pi source was privately reviewed and assembled into a portable source candidate; offline source/voice-dashboard syntax, historical-evidence, memory, and trip-shadow tests passed. However, **the updated source is not yet merged into GitHub's installer and no fresh Pi installation, upgrade or reboot recovery has been accepted**. See the [source audit and blocking checks](docs/V2_SOURCE_AUDIT_20261021.md). The [draft integration PR](https://github.com/prokyle123/tesla-intelligence-core/pull/4) remains separate from the production installer.

---

## Public v1.0 baseline (currently installable)

| Core intelligence | What it actually measures and learns |
| --- | --- |
| ❄️ **Winter readiness** | Overnight cold-soak, pack heating, module temperature, readiness for the next departure and thermal forecast ranges |
| 🔌 **Charging intelligence** | Tesla-reported charging input versus derived pack electrical power, slow Level 1 charging behavior, charging transitions and optional home-power context |
| 🌦️ **Outdoor weather** | Hourly Open-Meteo conditions and 3 / 6 / 12-hour weather forecasts alongside pack-temperature projections |
| 🚗 **Every-trip learning** | All observed drives, multi-leg journeys, short errands, weekends, charging stops and repeat routes—not just work commutes |
| 📉 **Forecast and journey quality** | Frozen forecasts compared against later observations; separate error, confidence, missing-data and invalid-comparison states |
| 🧠 **Machine-learning ecosystem** | Classical baselines, sequence neural challenger, model generations, held-out validation and governed production selection |
| 🛡️ **Read-only vehicle sensors** | Tessie TPMS pressure in PSI, Sentry, lock, charge port, cabin fan and stale-data flags when available |
| 🏠 **Local-first control plane** | Raspberry Pi systemd services, local SQLite telemetry and model files; vehicle-command functions intentionally excluded |

> [!IMPORTANT]
> **Winter impact and overnight charging are the original mission.** The broader driving models give thermal and departure forecasts realistic demand context. Readiness scores and model “confidence” displays are not proofs of cold-weather accuracy; real winter validation accumulates over time.

## Visual tour

All panels shown below are **screenshots of a running Ghost development system**. Private route identifiers in the departure screenshot were removed. Colors, model generations and instantaneous values vary by installation.

### 🧠 Neural Engine Atlas

<p align="center">
  <a href="docs/images/v1/v1-neural-engine.webp">
    <img src="docs/images/v1/v1-neural-engine.webp" alt="Neural engine showing temporal input lanes, GRU blocks, shared latent state, output heads and production governor" width="98%">
  </a>
</p>
<p align="center"><sub>Real-time sequence features, recurrent processing, multiple prediction heads and separate truth/governor paths.</sub></p>

<table>
<tr><td width="50%" valign="top">
<h3>❄️ Pack forecast + 3 / 6 / 12-hour weather</h3>
<a href="docs/images/v1/v1-pack-weather.webp"><img src="docs/images/v1/v1-pack-weather.webp" alt="Actual pack temperature outlook with hourly outdoor weather" width="100%"></a>
<p>Future pack temperature, outside air and estimated thermal margin, alongside current hourly weather forecast.</p>
</td><td width="50%" valign="top">
<h3>⚡ Thermal power path</h3>
<a href="docs/images/v1/v1-thermal-power.webp"><img src="docs/images/v1/v1-thermal-power.webp" alt="Wall power split into derived pack and non-pack electrical loads" width="100%"></a>
<p>Shows measured wall input and derived electrical power estimates. Differences are not proof of a specific heater load.</p>
</td></tr>
<tr><td valign="top">
<h3>🕒 Learned departure planning</h3>
<a href="docs/images/v1/v1-departure-planning.webp"><img src="docs/images/v1/v1-departure-planning.webp" alt="Learned departure and readiness card, with private site identifiers redacted" width="100%"></a>
<p>Trip-history timing priors, departure pack/SOC projection and conditional multi-leg energy demand.</p>
</td><td valign="top">
<h3>📊 AI Operations Workspace</h3>
<a href="docs/images/v1/v1-ai-workspace.webp"><img src="docs/images/v1/v1-ai-workspace.webp" alt="AI operations workspace showing readiness trends, promoted models and training evidence" width="100%"></a>
<p>At-a-glance operational readiness, training evidence, truth quality and per-model status.</p>
</td></tr>
<tr><td valign="top">
<h3>🧪 Model Lab</h3>
<a href="docs/images/v1/v1-models.webp"><img src="docs/images/v1/v1-models.webp" alt="Model Lab grid of production and collecting prediction models" width="100%"></a>
<p>Individual horizons, live output, model validation error, readiness trend and generation history.</p>
</td><td valign="top">
<h3>✅ Prediction Truth Lab</h3>
<a href="docs/images/v1/v1-truth-lab.webp"><img src="docs/images/v1/v1-truth-lab.webp" alt="Prediction Truth Lab trust and measured forecast-error dashboard" width="100%"></a>
<p>Frozen predictions are evaluated after the measurement arrives, including missed, pending and resolved results.</p>
</td></tr>
</table>

<details>
<summary><b>More screenshots: production selection and prediction safety</b></summary>
<p><a href="docs/images/v1/v1-production.webp"><img src="docs/images/v1/v1-production.webp" alt="Production model selection, live outputs and observation-only safety boundary" width="98%"></a></p>
<p>Promoted serving models and model-selection safeguards, with vehicle commands disabled.</p>
</details>

### System architecture

<p align="center">
  <a href="docs/images/v1-architecture.svg">
    <img src="docs/images/v1-architecture.svg" alt="Local-first vehicle telemetry, weather, private history, predictive models, independent evaluation and read-only dashboards" width="90%">
  </a>
</p>

> [!NOTE]
> v1.0 is initially published with **limited installation validation**. The major source consolidation and automated regression checks have passed, but a clean install on a second Raspberry Pi was not available for end-to-end verification. See [release notes](docs/V1_RELEASE_NOTES.md), [installation guide](docs/INSTALL.md) and [compatibility](docs/COMPATIBILITY.md).

---

## Android companion + in-car browser

Tesla Intelligence Core is not limited to a desktop browser.

### 📱 Android companion

The Android companion keeps the Pi dashboard as the source of truth while adding phone-focused discovery, failover, diagnostics, navigation and background alerts.

**Companion v0.9.1** uses one navigation surface only: a single horizontally swipeable dashboard-owned row.

```text
HOME · READY · EVENTS · NEURAL · TRUTH · THERMAL · MORE
```

The old duplicate Android navigation bar has been removed. The WebView is now explicitly padded for the real Android status/cutout and navigation/gesture insets so the companion bar stays above the phone's Home/Back/Recents area.

The Connection Center supports:

```text
Local LAN
    ↓ fallback
Private Tailscale
    ↓ fallback
Public HTTPS / PIN gateway
```

Configured routes are tested in parallel and the companion verifies the real dashboard API instead of treating any HTTP 200 page as data.

#### Background monitoring + notifications

v0.9.1 adds an Android JobService background monitor. Android wakes it approximately every 15 minutes when networking and OS scheduling allow, it checks the saved Tesla Intelligence Core routes, and then it goes back to sleep.

The Notification Center can independently enable:

- connection lost / restored;
- Winter Readiness threshold alerts;
- warm-up / preconditioning recommendations;
- projected arrival SOC threshold alerts;
- battery-heater activation.

The default readiness threshold is 70 and the default projected-arrival threshold is 20%. Both are editable in the app. A manual **Run Background Check Now** action and a test notification are included.

Background scheduling persists across reboot/package replacement and does not require an always-running foreground process.

**[Download Android Companion v0.9.1](https://github.com/prokyle123/tesla-intelligence-core/releases/download/v0.8.27.6/Tesla-Intelligence-Core-Companion-v0.9.1-debug.apk)** · **[Source + local installer](companion/android)**

> [!NOTE]
> The public companion APK is debug-signed. An older locally built copy may have a different Android signature. Rebuilding on the same PC normally reuses that PC's Android debug key and allows an in-place update without clearing the saved endpoints.

### 🚗 Open the dashboard in the Tesla browser

On the setup this project was developed with, the Tesla browser would not load the Pi's local/private dashboard address. A working route was:

```text
Tesla browser
      ↓  Internet HTTPS
Tailscale Funnel
      ↓
PIN gateway
      ↓
Tesla Intelligence Core
```

This is useful because the Tesla browser does not need direct access to the Pi's LAN address. If the Pi installation has working Internet access, Funnel is configured correctly, and the car has Internet access, the dashboard can be reached directly from the Tesla browser using the public HTTPS URL.

**Why the PIN?** Funnel makes that HTTPS endpoint reachable from the public Internet. The intended setup is **Funnel → PIN gateway → dashboard**, not Funnel directly to the raw dashboard.

Vehicle software, networks and installations can vary; this documents the project's tested setup rather than assuming every Tesla behaves identically.

**[Full Tesla browser + Funnel guide](docs/TESLA_BROWSER.md)**

---

## Why this project is different

### Most dashboards stop at telemetry. Tesla Intelligence Core keeps going.

A telemetry-only dashboard can tell you the battery is **82°F and 80% right now**.

Tesla Intelligence Core asks the harder questions:

> **What will that temperature be in three hours? What SOC will actually be available at departure? What will probably remain after the drive? Is this a routine departure or a random trip? How much evidence supports the answer? And when the future arrives, was the prediction right?**

It is built to turn a live snapshot into a continuously improving model of **your particular car, your charging setup, your routine, and what is likely to happen next**.

| | |
|---|---|
| **🧠 Learns your car** | Builds evidence about pack cooling, thermal retention, cold soak, charging behavior, trip energy use and other behavior from your own history instead of relying only on fixed assumptions. |
| **🕒 Learns your routine** | Finds repeated departure patterns from actual drive starts. A configured departure is only a fading prior, while random and secondary trips remain useful without taking over the routine. |
| **🔮 Forecasts multiple futures** | The neural engine consumes rolling telemetry sequences and produces multi-horizon outputs for **SOC, pack temperature and cabin temperature** rather than a single one-off estimate. |
| **🎯 Checks prediction against reality** | **Truth Lab** resolves old predictions when future telemetry arrives, so the system can measure what actually happened instead of displaying a forecast and forgetting it. |
| **🛡️ Governs its own models** | Challenger and production generations can be compared before promotion. The governor, promotion gates and rollback path are visible in the Neural Engine instead of being hidden behind an opaque “AI” label. |
| **❄️ Turns models into an answer you can use** | Winter Readiness combines live conditions, learned evidence and forecasts into a score with **human-readable limiters** showing exactly what is costing points. |
| **🔒 Local-first and read-only** | History, events and trained model artifacts live on your Pi. The project observes and predicts; it does not intentionally send driving, locking, charging or climate-control commands to the vehicle. |
| **🔌 More than one telemetry path** | Supports **Tessie API** and **TeslaMate MQTT**, with optional weather, EcoFlow, Starlink and Tailscale integrations around the core intelligence stack. |

### From raw telemetry to a closed learning loop

```text
Tesla telemetry
      ↓
Local SQLite history
      ↓
Trips · charging · thermal events · departure patterns
      ↓
Classical ML + PyTorch GRU sequence model
      ↓
Future SOC · pack temperature · cabin temperature
      ↓
Truth Lab: prediction → actual outcome
      ↓
Governor: challenger → promotion / hold / rollback
      ↓
Winter Readiness + human-readable limiters
```

### A telemetry view vs. Tesla Intelligence Core

| Telemetry-only view | Tesla Intelligence Core |
|---|---|
| Current SOC | **Projected departure SOC + projected arrival reserve** |
| Current pack temperature | **1h / 3h / multi-hour pack-temperature forecasts** |
| Drive history | **Learned recurring departure behavior** |
| Charging power | **Learned charging behavior + charge-deadline context** |
| Weather / outside temperature | **Cold-soak and thermal-margin evidence** |
| One model output | **Serving + challenger generations with promotion gates** |
| Prediction shown once | **Prediction later resolved against truth** |
| Generic status | **Explainable Winter Readiness with exact limiters** |

> **The goal is not to put an “AI” badge on a Tesla dashboard. The goal is to build a local system that learns, predicts, checks itself against reality, and gets more useful as it observes the car.**

---

## Highlights

### 🧠 Guarded local AI + voice (V6.6 development Pi)
- Qwen3.5 4B local model through llama.cpp; generation is asynchronous and cached
- Verified readings and selected historical context separate from generated prose
- Numerical and relational evidence guards plus trusted text fallback
- Browser voice reads verified status and optional AI explanations
- Top-of-hour announcements and independent rule-based anomaly alerts
- Hourly V6.2 memory journal and optional Qwen server watchdog
- **Not yet supplied by the public v1 installer** — [V2 pre-release](https://github.com/prokyle123/tesla-intelligence-core/releases/tag/v2.0.0-preview.1)

### ❄️ Winter Readiness
- 0–100 readiness score
- Human-readable **Winter Readiness Limiters**
- Exact point deductions instead of a mystery score
- Live pack, module, ambient, charging and departure context
- Projected pack temperature at departure
- Projected departure and arrival SOC
- Warm-up / preconditioning context
- Cold-soak and thermal-retention learning

### 🧠 Learned departures
- Learns actual drive-start behavior from telemetry
- Optional configured departure is only a **fading prior**
- Repeated routine departures gain weight naturally
- Random / secondary trips remain useful without dragging the main routine around
- Separate **schedule confidence** and **next-trip probability**


### 🔋 Battery + charging intelligence
- Pack / module temperature tracking
- Pack current, voltage and power context where available
- Charge-rate and **Level 1 behavior memory**
- Charging pace / deadline context for the next departure
- Projected departure SOC and **arrival reserve**
- Thermal margin and pack trend
- Battery-heater / HVAC / preconditioning observation
- Tesla-reported charging input vs derived pack / non-pack power (not independent wall-meter data)

### 📈 Prediction stack
- Scikit-learn baseline models
- PyTorch GRU temporal sequence model
- Challenger / shadow model workflow
- Promotion gates and rollback-oriented governor
- Prediction auditing / **Truth Lab**
- Model generations stored independently

### 🛰️ Telemetry + integrations
- **Tessie API**
- **TeslaMate MQTT**
- Tessie historical backfill
- Open-Meteo weather context
- Optional EcoFlow RIVER 3 telemetry
- Optional Starlink local power telemetry
- Optional Tailscale private access
- Optional PIN-protected Tailscale Funnel

### 🔒 Local-first
- SQLite history lives on your Pi
- Learned model artifacts stay on your Pi
- Credentials live outside the repository
- Public remote access is optional
- Raw dashboard and public PIN gateway use separate ports

---

# Quick start

## Recommended hardware

- **Raspberry Pi 5** recommended
- 64-bit Raspberry Pi OS or Debian
- Internet connection during install
- Python 3.11+
- One telemetry source:
  - **Tessie** account/API token, or
  - an existing **TeslaMate MQTT** broker

A Pi 4 or other 64-bit Debian-class machine may work, but the project is developed with Pi 5-class hardware in mind and neural training is the most CPU-intensive workload.

## One-command interactive install

> [!IMPORTANT]
> This command installs the public v1 baseline, **not** the current V6.6 guarded 4B system. Existing development installations should not be overwritten; the V2 installer is under integration testing. See [V2 release notes](docs/V2_RELEASE_NOTES_DRAFT.md).


```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prokyle123/tesla-intelligence-core/main/install.sh)
```

The installer asks for what it needs as it goes:

1. Linux service user
2. Timezone
3. Tessie or TeslaMate
4. Tessie token / optional VIN, or MQTT connection details
5. Optional departure-time seed
6. Historical backfill window
7. Dashboard port
8. Optional EcoFlow integration
9. Optional Starlink support
10. Optional PIN-protected Tailscale Funnel

It then installs dependencies, creates the Python environment, builds the systemd services/timers, initializes the database, starts collection + dashboard services, and can begin historical learning immediately.

> [!TIP]
> For Tessie users, a historical backfill lets the system begin learning from prior driving/charging behavior instead of waiting weeks from a completely empty database.

Full walkthrough: **[Installation guide](docs/INSTALL.md)**

---

# What happens after install?

Open:

```text
http://PI_ADDRESS:8766
```

The system begins collecting telemetry and gradually fills in the parts that require evidence.

You should expect some cards to show **LEARNING**, **THIN**, or lower confidence early on. That is intentional. Tesla Intelligence Core is designed to expose when it does *not* yet have enough history rather than pretending every estimate is equally strong.

Useful commands:

```bash
# System / data status
ghost-ai status

# Run an intelligence cycle now
ghost-ai intelligence

# Dashboard logs
sudo journalctl -u ghost-tesla-ai-web.service -f

# Collector logs
sudo journalctl -u ghost-tesla-ai-collector.service -f

# Neural training logs
sudo journalctl -u ghost-tesla-ai-neural.service -f
```

> [!NOTE]
> The public project name is **Tesla Intelligence Core**. Internal package, CLI and service names still use the original `ghost_tesla_ai`, `ghost-ai`, and `ghost-tesla-ai-*` names for compatibility with existing installs.

---

# How it works

```mermaid
flowchart TD
    A[Tessie API] --> C[Telemetry Collector]
    B[TeslaMate MQTT] --> C
    C --> D[(SQLite History)]
    D --> E[Event Intelligence]
    D --> F[Classical ML]
    D --> G[PyTorch GRU]
    E --> H[Departure Learning]
    E --> I[Cold-Soak / Charging / Trip Evidence]
    F --> J[Forecast Layer]
    G --> J
    H --> J
    I --> J
    J --> K[Winter Readiness + Limiters]
    K --> L[Flask Dashboard :8766]
    L --> M[Private LAN / Tailscale]
    L --> N[Optional PIN Gateway :8777]
    N --> O[Optional Tailscale Funnel]
```

### Data flow in plain English

1. **Collect** normalized telemetry from Tessie or TeslaMate.
2. **Store** it in local SQLite history.
3. **Extract events** such as drives, charging windows and thermal evidence.
4. **Learn behavior** such as recurring departures and cold-soak patterns.
5. **Train models** for future SOC / temperature behavior.
6. **Compare predictions against truth** as later telemetry arrives.
7. **Build readiness** from live state + learned evidence + forecasts.
8. **Explain the result** in the dashboard.

Deep dive: **[Architecture](docs/ARCHITECTURE.md)**

---

# The dashboard

The main dashboard is intentionally operational rather than just analytical.

### Winter Readiness
The hero card answers whether the car appears ready for the next expected trip. If the score is not 100, the **Winter Readiness Limiters** show the actual reason and point hit.

Examples of limiter-style conditions include:
- pack forecast below target;
- low projected arrival reserve;
- insufficient departure charge;
- thin commute evidence;
- thin cold-soak history;
- low evidence confidence.

### Departure + workday plan
Shows the learned next-departure context, departure SOC, projected arrival SOC, expected pack temperature and preconditioning/warm-up context.

### Neural Engine
Shows prediction/model state separately from the readiness score. Readiness is an operational score; model metrics are model-performance evidence.

### Truth Lab / history
Provides the deeper validation side of the project: what the system predicted versus what later happened.

---

# Telemetry sources

## Tessie
Best fit when you want:
- live API telemetry;
- historical backfill;
- an easy way to seed learning on a new install.

The installer stores the Tessie token at:

```text
/etc/ghost-tesla-ai/tessie.token
```

## TeslaMate MQTT
Best fit when you already run TeslaMate and want Tesla Intelligence Core consuming the MQTT stream.

You provide:
- broker host;
- port;
- TeslaMate car ID;
- optional MQTT username/password;
- optional TLS.

See **[Configuration](docs/CONFIGURATION.md)** for details.

---

# Data, privacy and security

Vehicle telemetry can reveal extremely personal patterns: when you leave, where your routines occur, charging habits, and potentially location-related information contained in provider payloads.

Default storage:

```text
Code       /opt/ghost-tesla-ai
Config     /etc/ghost-tesla-ai/ghost.env
Tessie     /etc/ghost-tesla-ai/tessie.token
Database   /var/lib/ghost-tesla-ai/ghost_ai.sqlite3
Models     /var/lib/ghost-tesla-ai/models
```

The repository ignores runtime databases, environment files, tokens, trained artifacts and logs.

Read before exposing anything publicly:

- **[Privacy](PRIVACY.md)**
- **[Security](SECURITY.md)**
- **[Remote access](docs/REMOTE_ACCESS.md)**

### Remote access model

Private access:

```text
Your device -> Tailscale -> Pi:8766
```

Optional public path:

```text
Internet HTTPS
      ↓
Tailscale Funnel
      ↓
127.0.0.1:8777
      ↓
PIN gateway
      ↓
127.0.0.1:8766
```

Do **not** point a public Funnel directly at `8766` if you expect the PIN gateway to protect the dashboard.

---

# Updating

If you cloned the repository:

```bash
git pull
./update.sh
```

Runtime history, model artifacts and secrets live outside the code tree and are preserved by the installer/update path.

See **[Installation → Updating](docs/INSTALL.md#updating)**.

---

# Uninstalling

From the repository:

```bash
./uninstall.sh
```

The uninstaller asks before removing learned data, models and configuration.

---

# Project status

**Stable installable release: v1.0.0. New development preview: [v2.0.0-preview.1](https://github.com/prokyle123/tesla-intelligence-core/releases/tag/v2.0.0-preview.1) — GHOST V6.6 local Qwen3.5, voice alerts, verified memory and AI insight.**

The V2 pre-release is a **feature showcase, not yet a complete V2 installer**. A working Pi deployment has those features; a portable new-install/upgrade path is being reconciled and tested separately.

This is an experimental enthusiast project, not a Tesla product and not a safety system.

Predictions are estimates. Do not treat them as guarantees of:
- battery temperature;
- remaining range;
- charging completion;
- departure timing;
- vehicle operation.

Development/testing has primarily centered on **Model 3 telemetry**. The code is not intentionally locked to one Tesla model, but different vehicles/providers may expose different signals.

If you run it on another Tesla, a compatibility report is genuinely useful.

---

# Documentation

| Guide | What it covers |
|---|---|
| **[Use cases](docs/USE_CASES.md)** | Winter commuting, Level 1 charging, cold soak and other real-world scenarios |
| **[Feature matrix](docs/FEATURE_MATRIX.md)** | What each feature uses and what question it answers |
| **[V2 preview release](https://github.com/prokyle123/tesla-intelligence-core/releases/tag/v2.0.0-preview.1)** | New guarded 4B intelligence, voice alerts, verified memory and current screenshot |
| **[V2 full change notes](docs/V2_RELEASE_NOTES_DRAFT.md)** | Feature-by-feature development history and pending installer migration |
| **[AI architecture](docs/GHOST_INTELLIGENCE_V2.md)** | Separate numerical learning, memory, local-language-model narration and fallbacks |
| **[Changelog](CHANGELOG.md)** | v2 preview changes and earlier releases |
| **[Install](docs/INSTALL.md)** | Full fresh-install walkthrough and validation |
| **[Configuration](docs/CONFIGURATION.md)** | Environment settings and data paths |
| **[Architecture](docs/ARCHITECTURE.md)** | Collector → learning → models → readiness |
| **[Remote access](docs/REMOTE_ACCESS.md)** | Tailscale and PIN-protected Funnel |
| **[Tesla browser](docs/TESLA_BROWSER.md)** | In-car browser access through the optional HTTPS Funnel + PIN gateway |
| **[Android companion](companion/android/README.md)** | Mobile app, endpoint failover, current views and local build instructions |
| **[Troubleshooting](docs/TROUBLESHOOTING.md)** | Services, logs, common install/runtime problems |
| **[FAQ](docs/FAQ.md)** | Common project questions |
| **[Compatibility](docs/COMPATIBILITY.md)** | What is known/tested and how to report results |
| **[Roadmap](ROADMAP.md)** | Current development directions and community priorities |
| **[Support](SUPPORT.md)** | What to include when asking for help |
| **[Privacy](PRIVACY.md)** | Data-handling expectations |
| **[Security](SECURITY.md)** | Secrets and remote-exposure guidance |
| **[Contributing](CONTRIBUTING.md)** | Issues, PRs and safe telemetry sharing |
| **[Code of Conduct](CODE_OF_CONDUCT.md)** | Community participation expectations |
| **[Citation](CITATION.cff)** | Citation metadata for research / derived work |
| **[Changelog](CHANGELOG.md)** | Release history |

---

# Contributing

Useful contributions include:
- field reports from other Tesla models;
- Tessie / TeslaMate normalization fixes;
- cold-climate thermal observations;
- Pi performance improvements;
- model/truth-audit improvements;
- dashboard usability work;
- synthetic/redacted test data.

Please **do not** post VINs, exact locations, tokens, raw private telemetry or credentials in public issues.

Start here: **[CONTRIBUTING.md](CONTRIBUTING.md)**

Running Tesla Intelligence Core on a different Tesla model? **[Open a vehicle compatibility report](https://github.com/prokyle123/tesla-intelligence-core/issues/new?template=compatibility.yml)** — even a partial compatibility report helps map which telemetry signals are available across the fleet.

### Help the project get found

GitHub discovery is driven less by hashtags and more by **repository Topics, stars, forks, useful releases, links, README search terms and community activity**.

If Tesla Intelligence Core solves a real problem for you:

- ⭐ **Star it** so other Tesla / EV owners are more likely to find it.
- 🧪 Submit a **compatibility report** for your vehicle.
- 🐛 Open a reproducible issue when something breaks.
- 🔀 Send a pull request if you improve normalization, models, docs or the dashboard.
- 🔗 Share the repository with people working on TeslaMate, Tessie, Raspberry Pi, EV charging or cold-weather telemetry.

---

# License

MIT — see **[LICENSE](LICENSE)**.

---

<div align="center">

### Built for people who need more than a battery percentage — and want to know what their Tesla is likely to do next.

**Tesla Intelligence Core is unofficial and is not affiliated with or endorsed by Tesla, Tessie, EcoFlow, Starlink, Tailscale, or Open-Meteo.**

Product and service names belong to their respective owners.

</div>
