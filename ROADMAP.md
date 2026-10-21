# Roadmap

Tesla Intelligence Core is an experimental enthusiast project. This roadmap describes useful directions, not guaranteed dates or commitments.

## Major V2 release candidate: guarded local intelligence

- Reconcile production dashboard and all independent intelligence sidecars with versioned, portable source.
- Provide an optional Qwen3.5 4B install with an explicit model/llama.cpp dependency path, device-capability checks, cache timeouts, verified fallback and watchdog rollback.
- Keep trained prediction models, hourly memory, optional narration, immediate alerts and verified measurements as separate layers.
- Validate fresh Pi installation and upgrade/rollback without removing current dashboard features or changing saved vehicle data.
- Prove long-run performance and post-reboot recovery; do not confuse accepted AI prose with numerical model accuracy.
- [Release requirements and current blockers](docs/V2_RELEASE_GATES.md).

## Near-term

- Expand compatibility reports across Model S / 3 / X / Y.
- Improve telemetry normalization differences between Tessie and TeslaMate.
- Keep improving the fresh-install experience.
- Add more synthetic/redacted test fixtures.
- Improve Truth Lab visibility and model-audit summaries.
- Improve dashboard behavior on phones and in-car browsers.
- Continue refining thermal / charging evidence quality.
- Document more real-world slow-charging and cold-weather cases.

## Model / intelligence work

- Continue evaluating temporal model generations.
- Improve challenger vs production comparisons.
- Expand explainability around why forecasts move.
- Track calibration / uncertainty as more truth data accumulates.
- Continue separating "routine schedule quality" from "next-trip confidence".
- Improve sparse-data behavior for new installs.

## Community-driven work

The most valuable outside contributions are likely to be:

- compatibility reports from different Tesla models and years;
- field behavior from colder/warmer climates;
- TeslaMate signal mapping differences;
- charging setups beyond Level 1;
- performance observations on Pi 4 / Pi 5 / other ARM systems;
- redacted telemetry edge cases.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).
