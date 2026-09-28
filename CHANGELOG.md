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
- Android Companion v0.2.0 source is included under `companion/android`.
- Public APK, checksum and source ZIP are attached to the v0.8.27.6 GitHub release.
- Companion supports Local LAN → private Tailnet → optional public HTTPS failover.
- Current dashboard views are available from the companion, including AI Lab, Models, Data Quality, Sources, Events, Neural Engine, Truth Lab, Thermal History, Production and History.
- Dedicated Tesla in-car browser guide documents the tested HTTPS Funnel → PIN gateway → dashboard path.
- Fresh public companion installs no longer contain developer-specific IP/Tailscale defaults.

### Public repository
- Interactive fresh installer.
- Runtime config/data kept outside the source tree.
- Privacy/security docs.
- GitHub smoke workflow.
