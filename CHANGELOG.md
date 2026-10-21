# Changelog

## Current development update (2026-10-20) — not yet a tagged V2 release

- Replaced the main README dashboard preview with an authentic screenshot of the running GHOST V6.6 dashboard.
- Updated the current-development feature table to cover local guarded Qwen3.5 4B narration, independent voice alerts, Tessie historical comparisons, verified memory, winter readiness and fail-closed commentary.
- Corrected public language distinguishing Tesla-reported charge input from independently measured wall power.
- The new screenshot and descriptions do **not** imply the public v1.0 installer deploys the V6.6 intelligence sidecars; source, portability, and rollback reconciliation remains in draft PR #4.
- Kept exploratory ambient-context thermal models out of production after inferior historical holdout performance.

---


## v1.0.0 — Major winter & whole-vehicle intelligence release (2026-10-16)

### Delivered features (new-install hardware test deferred)

- Synced 26 live application source changes into a draft PR and integrated vehicle-sensor, Forecast Quality v2, and Trip Quality v3.2.1 endpoints.
- Added all-journey/weekend summary alongside time-of-day context. Charge sessions already in progress when a forecast was frozen no longer automatically invalidate that forecast; newly initiated unverified charging still blocks comparisons.
- Added portable on-Pi paths for sidecar reports and trip registries; scheduled independent hourly quality evaluation and a 30-minute six-stage shadow trip-learning pipeline.
- Added package-relative import fixes and regression tests for all trip-shadow layers.
- Updated the project GitHub page, draft installation documentation, feature matrix, release notes, an architecture illustration, and private screenshot capture instructions.
- **Intentionally not done:** fresh Pi installation, active Ghost upgrade/reboot validation, current-production screenshot publication, or public v1.0.0 tag.



- Audited the current Ghost development Pi against public `main`: 33 matching source files, 12 modified tracked files, and 14 new source/evaluator files; the existing `requirements.txt` was not part of that comparison.
- v1.0 scope covers winter/overnight charging readiness, all-trip energy learning, multi-leg trip reconstruction, shadow forecast-truth evaluation, tire-pressure/Sentry/vehicle sensor monitoring, Open-Meteo hourly outlook, and a first-install / upgrade workflow.
- Started source-only staging and secret review. Systemd unit templates and independent clean install tests **remain release blockers**.
- Improved draft installer so existing credentials are detected before setup prompts, and installed features missing from the checkout are not silently removed.

**Validation limitation:** Automated regression and source checks passed; a new Raspberry Pi installation and in-place upgrade/reboot validation were not completed before release. See [release notes](docs/V1_RELEASE_NOTES.md).


Notable changes to **Tesla Intelligence Core (GHOST)**, grouped by development snapshot or public release.

[Project overview](README.md) · [October 2026 detailed update](docs/OCTOBER_2026_UPDATES.md) · [Releases](https://github.com/prokyle123/tesla-intelligence-core/releases)

> [!NOTE]
> **October 2026 is a live-source development snapshot, not a new published release or version tag.** The previous public release remains **v0.8.27.6**. Runtime service configuration, private telemetry and trained model artifacts are not part of the October GitHub sync.

---

## October 11, 2026 — Live GHOST development sync

**Status:** Source synchronized from the running Raspberry Pi to the public repository. See the [full October feature breakdown](docs/OCTOBER_2026_UPDATES.md).

### Highlights

| Feature area | What's new or improved |
| --- | --- |
| **Winter Readiness** | One gauge switches between current conditions and next-departure predictions, with mode-specific explanations and recorded trends |
| **Trip learning** | Six independent shadow layers measure trips, locations, predicted outcomes and forecast accuracy |
| **Departure planning** | Recurring multiple-trip patterns and automatic rollover to the next supported departure |
| **Charging** | Guard against DC fast-charging sessions affecting the learned Level 1 charging rate |
| **Models** | Continued baseline-versus-neural evaluation and production promotion safeguards |
| **Privacy** | Source-only publishing; runtime vehicle data and credentials stay off GitHub |

### Added

- **RIGHT NOW Winter Readiness mode.** Separately calculates a score from currently measured SOC and pack temperature, current conditions and a **conditional reference-trip reserve**; the reference trip is **not location-verified**.
- **Mode selector for the existing dial.** Switch between **RIGHT NOW** (default) and **NEXT DEPARTURE**, keeping the original one-gauge layout.
- **Independent NOW score history.** The right-side trend graph follows the selected mode. The existing projected-score history is retained; the new NOW history accumulates real observations after installation.
- **Six shadow trip-learning layers:**
  - **v1:** Drive sequences, anonymous parking zones and recurring chains.
  - **v2:** Stable site identities and observed relationships; nearby places are not automatically merged.
  - **v3.2:** Prospective route forecasts frozen before driving and scored against complete outcomes.
  - **v4:** Verified timing, destination and SOC feedback; advisory only.
  - **v5:** Time-only departure evaluation when route evidence is unavailable.
  - **v6:** Unified comparison of route and time-only outcomes, including deduplication.
- **Conditional 24-hour trip-energy preview.** Estimates SOC demand for supported multi-leg patterns without asserting an unknown route or changing production readiness.
- **Background Winter Score sampling code.** Enables score capture beyond dashboard viewing when its optional systemd timer is enabled; timer state is deployment-specific.
- **October 2026 development documentation** with a source map, safeguards and verification notes.

### Improved

- **Adaptive departure behavior:** Supports recurring morning, afternoon and other adequately supported departure patterns, including selection of another upcoming candidate when one expires.
- **Readiness presentation:** Keeps current-state and forecast-state explanations separate rather than presenting a projected score as an instant leave-now measurement.
- **Model accountability:** Existing neural challenger/governor and prediction auditing continue to compare candidates against baseline models and held-out evidence. A new training generation does **not** automatically promote.
- **Reproducibility:** Exported the Python application and current dashboard from the *running Pi*, rather than reconstructing current source from older installers.

### Fixed

- **Supercharger / Level 1 learning contamination** in the charging event engine:
  - Positive charger power can no longer be hidden by a zero AC-input reading during event reconstruction.
  - Level 1 samples are screened using power, energy-over-time and SOC-rate plausibility checks.
  - In the October 9 installation check, accepted low-power examples changed from **55 to 53**, and the learned median moved from **1.385 to 1.374 SOC percentage points/hour**.
  - All historical high-power events remain recorded; the fix does **not** erase data or retrain models.

### Safety and compatibility notes

- No new vehicle-control functionality; forecasts remain **read-only and advisory**.
- Shadow trip-learning layers are **not** automatically wired into production readiness or neural serving.
- No private SQLite databases, credentials, location registries, model weights or live systemd unit definitions were uploaded.
- Existing public screenshots were retained. They may predate the October interface and are **not** presented as fresh captures.
- The source-export check passed Python syntax validation for **44 files**; a separate fresh-install test is still needed to validate complete deployment.

**Source synchronization commit:** [741ff0d](https://github.com/prokyle123/tesla-intelligence-core/commit/741ff0da322ad30452f20e756a548293ce380e04)

---

## v0.8.27.6 — First consolidated public release

**Status:** Previously published public release. Consolidates the original internal development patch series into a fresh-installable repository.

### Winter Readiness and thermal intelligence

- Operational **Winter Readiness Score** with pack, departure and expected arrival context.
- Human-readable **Winter Readiness Limiters** and explicit point deductions.
- Current pack temperature, ambient conditions and charging status alongside future thermal outlook.
- Cleaned-up main readiness cockpit layout and additional live thermal/charging context.

### Departure learning

- Learned departures from historical drive events.
- Configured departure time as a **fading prior**, not a permanent override.
- Routine, secondary and random-trip weighting.
- Separate departure probability and schedule confidence.
- Departure context introduced for newer neural models while retaining compatibility with existing model artifacts.

### Predictive models and accountability

- Conventional machine-learning prediction paths and PyTorch GRU temporal engine.
- Challenger/serving generation workflow with neural governor and promotion safeguards.
- Prediction auditing and Truth Lab for comparing forecasts against observations.

### Vehicle data, connectivity and operations

- **Tessie API** and **TeslaMate MQTT** telemetry sources, with Tessie historical backfill.
- Event intelligence for trips, charging and thermal history.
- Optional River 3 and Starlink telemetry integrations.
- PIN-protected Tailscale Funnel gateway for supported remote access.
- Interactive public installer, runtime-data separation, security/privacy documentation and GitHub smoke workflow.

### Android companion and Tesla in-car browser

- Android companion source under [companion/android](companion/android), with the public APK and source ZIP attached to the [v0.8.27.6 release](https://github.com/prokyle123/tesla-intelligence-core/releases/tag/v0.8.27.6).
- Connection Center with **LAN → private Tailscale → optional public HTTPS/PIN** fallback.
- Connection tests against the actual dashboard API, not merely an HTTP 200 response; PIN-gateway authentication is recognized and rechecked afterward.
- Native **HOME / READY / EVENTS / NEURAL / TRUTH / THERMAL** navigation based on dashboard URLs, replacing fragile injected JavaScript navigation.
- **HOME** opens the main overview; **READY** focuses the Winter Readiness hero.
- Clear selected navigation and safer phone status-bar/cutout/gesture-inset layout.
- WebView synchronization improvements: separate API connectivity from render status and address false **NO RENDER / {}** diagnostics.
- Dashboard access to AI Lab, Models, Data Quality, Sources, Events, Neural Engine, Truth Lab, Thermal History, Production and History.
- Tesla-browser setup instructions for the HTTPS Funnel → PIN gateway → dashboard path.
- Single horizontally swipeable dashboard navigation row (replacing the duplicate native bottom bar).
- Background Android JobScheduler monitoring, persistent across reboot/package replacement where permitted by Android.
- Notification Center for connection changes, readiness thresholds, projected arrival SOC, warm-up recommendations and battery-heater activation.
- Manual background check and test notification.
- No developer-specific IP or Tailnet defaults in fresh public companion installs.

---

### About this history

- **Release** entries describe publicly tagged versions.
- **Development snapshot** entries describe subsequently synchronized code, which may depend on additional local service/timer configuration.
- For feature-level evidence and current known limitations, read the [October 2026 development update](docs/OCTOBER_2026_UPDATES.md).
