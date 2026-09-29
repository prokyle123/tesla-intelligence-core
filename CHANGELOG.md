# Changelog

## 0.8.27.6 — first consolidated public release

This release turns the internal development patch chain into a fresh-installable public repository.

### Readiness
- Winter Readiness Score.
- Human-readable **Winter Readiness Limiters** with exact score deductions.
- Pack/departure/arrival context in the main readiness view.
- Readiness cockpit layout cleanup.

### Departure learning
- Learned departure scheduling from observed drive history.
- Configured departure used as a fading prior rather than a permanent override.
- Routine / secondary / random trip weighting.
- Next-trip probability and schedule confidence.
- Departure context added to newer neural generations while retaining backward compatibility with existing model artifacts.

### Learning / prediction
- Classical ML prediction paths.
- PyTorch GRU temporal engine.
- Challenger / serving generation workflow.
- Neural governor / promotion logic.
- Prediction auditing / Truth Lab.

### Telemetry / operations
- Tessie API source.
- TeslaMate MQTT source.
- Tessie historical backfill.
- Event intelligence.
- River 3 optional integration.
- Starlink optional telemetry.
- PIN-protected Tailscale Funnel gateway.

### Companion / in-car access
- Android Companion v0.4.0 source is included under `companion/android`.
- Public APK, checksum and source ZIP are attached to the v0.8.27.6 GitHub release.
- Companion supports Local LAN → private Tailnet → optional public HTTPS/PIN failover.
- Connection Center can discover the Pi on the local network and verifies the real dashboard API instead of trusting an HTTP 200 page.
- Public PIN-gateway pages are recognized as authentication, then re-verified after login.
- Native READY / EVENTS / NEURAL / TRUTH / THERMAL navigation now switches dashboard views directly with a DOM fallback.
- Selected native navigation is highlighted and the phone header uses a two-row safe-area-aware layout.
- Fixed the false `NO RENDER` / `{}` state caused by treating an asynchronous WebView Promise as the finished render result.
- Dashboard synchronization now treats API connectivity and WebView rendering as separate states, with per-route and JavaScript diagnostics.
- Current dashboard views include AI Lab, Models, Data Quality, Sources, Events, Neural Engine, Truth Lab, Thermal History, Production and History.
- Dedicated Tesla in-car browser guide documents the tested HTTPS Funnel → PIN gateway → dashboard path.
- Fresh public companion installs contain no developer-specific IP/Tailscale defaults.

### Public repository
- Interactive fresh installer.
- Runtime config/data kept outside the source tree.
- Privacy/security docs.
- GitHub smoke workflow.
