# GHOST Intelligence V2 — full upgrade release notes (DRAFT)

**Status:** **Source integration in progress. Not a public release, tag, or drop-in upgrade yet.**
**Observed development milestone:** October 20, 2026 — Qwen3.5 4B guarded production narration on Raspberry Pi 5.

[Latest dashboard screenshot](images/ghost-v2-dashboard-live.webp) · [Integration PR](https://github.com/prokyle123/tesla-intelligence-core/pull/4) · [V2 release gates](V2_RELEASE_GATES.md) · [Architecture](GHOST_INTELLIGENCE_V2.md)

This document tracks the features planned for the next major release. It distinguishes features **verified on the development Pi** from those **already reproducible with the public GitHub installer**. A green development-service status is not proof of an independently tested public installation.

## At a glance

GHOST combines three separate kinds of intelligence:

1. **Numerical and sequence prediction models** — classical and neural trip/thermal/charging forecasts, independent model generations, holdout/truth evaluation and readiness scores.
2. **Verified evidence, memory and alert logic** — Tessie/vehicle state, historical comparisons, hourly snapshots, direct heater/HVAC/charging sensor distinctions, and fast anomaly checks.
3. **Optional local LLM commentary** — Qwen3.5 4B explains selected evidence conversationally, with numerical/relational claim guards and deterministic verified fallback. The language model does not autonomously update its own weights.

Vehicle telemetry is used in **read-only** mode. No vehicle commands are sent by the intelligence/narration layer.

## Dashboard and spoken intelligence

| Area | Current development capability | What a public release must provide |
| --- | --- | --- |
| AI Insight compact panel | Current verified readings alongside optional model commentary and controls for expanding/full AI | Current live template/JavaScript, semantic data sources, graceful no-LLM state |
| Voice controls | Spoken verified status, optional deeper AI analysis, browser voice ON by default, user controls | Permissions handling and browser compatibility tests |
| Hourly speech | Brief readout at top of local clock hour (when enabled and browser permits speech) | Does not depend on the slower 4B inference succeeding |
| Real-time alerts | Multi-signal charging/thermal/status rule checks with voiced warnings and history | Rule-based delivery remains fast; sourced evidence and false-positive controls |
| Right Now readiness | Separate current-state score and 12-hour history | Preserve current-reading-only calculations and limitations |
| Next Departure | Learned future departure/scores/SOC/pack forecasts | Keep predictions clearly separate from current measurement |
| Forecast outlook | 1 h, 3 h, 6 h and coldest-forecast time plus Open-Meteo context | Show error intervals **only after validated calibration** |
| Battery heater/HVAC | Direct heater sensor versus vehicle conditioning/cabin climate flag, observed module temperatures | No indirect HVAC signals mistaken for confirmed battery heating |
| Electrical power | Tesla-reported charging input, derived pack flow and non-pack estimate | **Not** advertised as verified wall-meter measurements |

The [authentic dashboard image](images/ghost-v2-dashboard-live.webp) shows the latest local UI. Snapshot telemetry is a point-in-time example, not a universal measured result or an accuracy guarantee.

## Historical intelligence: V5–V6.5

- **V5 Tessie Deep Signals:** Separate charging power context, pack/module temperatures, direct heater/HVAC observations, and qualified historical comparison groups. Never infer an independent meter reading from reported Tesla input watts.
- **V6.1 historical retrieval pilot:** Investigated context-aware factual narration and guarded numeric evidence. Language-model fine-tuning/weight updates are **not** part of this feature.
- **V6.2 verified hourly memory:** Separate local hourly snapshot journal for historical comparison. Autonomous evidence capture is not trained LLM weights.
- **V6.3–V6.4.4a validation:** Iteratively improved category separation, guarded arithmetic, two-snapshot pack differences, uncertainty language, module-spread median relationships and negation-aware claims. Incorrect comparison claims are rejected instead of promoted as fact.
- **V6.4.3 handoff fix:** The shadow evaluator waits for a currently running 0.6B briefing to finish before model switching; a disabled timer alone does not stop an in-flight request.
- **V6.5 thermal history lab:** Read-only evaluation of continuous, passive thermal windows. One 90-day audit found 340 qualified windows: charging 247/18 days, unplugged 68/11 days, charge-complete 25/4 days. These samples do not prove independent predictive accuracy.
- **V6.5.1 numerical model experiment:** Chronological/day-purged, day-balanced thermal holdout. In charging-passive exploratory holdout, ambient-context regression had **1.419°F** day-balanced MAE versus **1.215°F** for the best simple comparison, and was **not promoted**.

The forecast interval recorder separately collects later observed outcomes. Blank/uncalibrated error bands are preferable to unsupported ranges.

## Guarded language model: V6.6

- Optional Qwen3.5 4B Q4_K_M running locally through llama.cpp on a development Raspberry Pi 5 (8 GiB).
- Historical evidence and memory are selected by code before the model generates prose. Numeric claims, module-spread comparisons and unsupported trend/fault-free claims are checked afterward.
- A rejected explanation returns a **verified fallback briefing**; it is not shown as factual AI commentary. Server health and installation errors have separate rollback handling.
- Briefing is generated asynchronously and cached approximately hourly, reducing pressure on the dashboard and preserving fast alerts.
- A watchdog checks the local model endpoint, with a retained 0.6B fallback configuration. An initial watchdog path mismatch was repaired on the development Pi. End-to-end automatic failure recovery remains a release validation gate.
- Initial live 4B production narration passed the claim guard (approx. **120 seconds** inference). The healthy-model check succeeded; long-running performance and unattended reboot recovery still require observation.
- GGUF weights/llama.cpp binaries are **not bundled** and are subject to their own licensing, setup and resource checks. Fresh GitHub installs must not silently download multi-GB model files or enable a heavy service.

## Preserved earlier capabilities

The new release must retain the existing v1 core rather than replace it:

- Tessie or TeslaMate MQTT read-only collection, local SQLite persistence, privacy controls, optional Tailscale PIN gateway.
- Classical scikit-learn and PyTorch sequence/GRU predictive models, neural generations, candidate governance, Truth Lab and model audits.
- Charging scenarios, Level 1 slow charging behavior, parked thermal history, preconditioning evidence, conditioning-vs-heater safeguards.
- Right Now and Next Departure readiness with distinct histories, SOC/pack forecasts, limiters, departure learning, arrival reserve estimates.
- All observed trips, weekends, errands, multi-leg behavior, and six isolated trip shadow learning components, plus separate forecast/trip-quality evaluators.
- Open-Meteo weather forecasts, optional EcoFlow/Starlink context where configured, in-car/phone-friendly web UI.

## Breaking changes and upgrade policy

**Do not assume this draft is installable over an existing Pi.** The public v1 installer currently replaces application directories, while the developer Pi contains newer code and separate Intelligence services. V2 must ship a tested migration that verifies the source tree, takes backups, stages changes, preserves configuration/history/models, deploys correct service users/paths and offers complete rollback.

Desired install layout: core under a user-configurable application directory (backwards-compatible with `/opt/ghost-tesla-ai`), optional intelligence independently managed, runtime history outside the checkout, model files outside the repository, systemd units generated from portable templates. Voice and AI narration should remain optional and should not block basic readiness.

## Still required before public v2.0

- Export and reconcile current Pi application + latest dashboard + independent intelligence source, after privacy/credential review.
- Implement a versioned portable optional AI installer, updater, tests, service/timer templates, dependency docs and explicit 0.6B/4B fallback.
- Test a fresh Raspberry Pi OS installation, upgrade from public v1, snapshot/rollback, model/server failures, browser voice permissions and resource use.
- Verify and publish accurate new screenshots, full help/feature matrix, installation instructions and changelog.
- Run security checks and CI, then merge/test/tag and publish release assets only after acceptance.

See [complete acceptance checklist](V2_RELEASE_GATES.md).
