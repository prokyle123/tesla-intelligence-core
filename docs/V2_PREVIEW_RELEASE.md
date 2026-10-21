# Tesla Intelligence Core v2.0.0-preview.1
### GHOST V6.6 local AI, verified memory & voice alerts — development preview

> **PRE-RELEASE — NOT A COMPLETE INSTALLABLE V2 BUILD.**
> The current developer Raspberry Pi runs the larger Qwen3.5 4B explanation engine, but this GitHub revision still uses the public **v1.0 installer**. Installing or upgrading from this preview will **not** recreate the entire V6.6 intelligence stack. Do not run it over a working developer installation.

## What's new on the current development GHOST

- **Qwen3.5 4B via local llama.cpp:** optional asynchronous, cached natural-language analysis explaining verified Tesla charging, pack temperature and separate readiness scores.
- **Evidence-validated AI:** numeric/relational guards reject unsupported claims, false module-spread comparisons, unwarranted sustained trends, invented numbers and unjustified fault-free claims; deterministic verified text is the fallback.
- **Voice & smart alerts:** browser spoken verified readings, optionally spoken AI analysis, on-the-hour updates and independent rule-based thermal/charging/status alerts.
- **V5 historical Tessie insights + V6.2 verified hourly memory:** charging-power and module-temperature historical context, direct battery-heater/HVAC separation and local timestamped observations. Memory retrieval is not language-model weight retraining.
- **Readiness dashboard expansion:** distinct **RIGHT NOW** and **NEXT DEPARTURE** scores, live battery/heater/cabin state, pack outlook, Open-Meteo outdoor forecast, and vehicle-reported versus derived pack power.
- **Shadow reliability improvements:** Qwen model handoff waits for active briefings to finish; current 4B has a watchdog health check and a retained smaller model rollback configuration. Full autonomous crash/restart/rollback behavior is still under test.
- **Ambient thermal model research:** 90-day descriptive analysis and chronological holdout of qualified parked windows. The experimental ambient predictor performed worse than the simple baseline and **was not promoted**.

## Genuine latest screenshot

[See the actual current development dashboard](https://github.com/prokyle123/tesla-intelligence-core/blob/main/docs/images/ghost-v2-dashboard-live.webp)

## Source and installation status

- This preview is meant to document and show the significant development update, **not to replace the user's running Pi installation**.
- The existing GitHub installer still targets v1.0.0. The latest 4B model/voice/source modules and services are being reconciled in [PR #4](https://github.com/prokyle123/tesla-intelligence-core/pull/4).
- A private source review bundle was obtained from the live Pi; it is not published unreviewed because it contains environment-specific paths and review-only IP redactions.
- No GGUF weights, personal vehicle readings, private routes, API tokens or environment files are included.
- The full V2 upgrade will follow after source migration, portable service templates, model dependency installation, security review, clean Raspberry Pi installation, and rollback testing.

## Further details

[Complete changelog](https://github.com/prokyle123/tesla-intelligence-core/blob/main/CHANGELOG.md) · [Feature matrix](https://github.com/prokyle123/tesla-intelligence-core/blob/main/docs/FEATURE_MATRIX.md) · [V2 architecture](https://github.com/prokyle123/tesla-intelligence-core/blob/main/docs/GHOST_INTELLIGENCE_V2.md) · [Full upgrade notes](https://github.com/prokyle123/tesla-intelligence-core/blob/main/docs/V2_RELEASE_NOTES_DRAFT.md) · [Blocking release gates](https://github.com/prokyle123/tesla-intelligence-core/blob/main/docs/V2_RELEASE_GATES.md)
