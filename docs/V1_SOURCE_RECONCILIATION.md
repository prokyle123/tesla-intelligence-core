# Live Ghost source reconciliation — 2026-10-15

> **Release engineering evidence, not a shipping claim.** A private source-only snapshot of the running Ghost Pi was compared with public Git blob hashes from `main`. No runtime data or source archive was uploaded to GitHub by this audit.

## Comparison results

| Classification | Count |
| --- | ---: |
| Byte-for-byte identical public files | **33** |
| Existing files modified on live Pi | **12** |
| Live source files not present in public repository | **15** |
| Total files in snapshot source inventory | **60** |
| Installed service/unit **names** inventoried | **20** |

12 modified tracked source files:

```text
ghost_tesla_ai/event_engine.py
ghost_tesla_ai/features.py
ghost_tesla_ai/funnel_pin_setup.py
ghost_tesla_ai/readiness.py
ghost_tesla_ai/server.py
ghost_tesla_ai/trainer.py
ghost_tesla_ai/trip_coverage_v5.py
ghost_tesla_ai/trip_outcome_v3.py
ghost_tesla_ai/winter_board.py
ghost_tesla_ai/winter_dual_mode_v1.py
ghost_tesla_ai/winter_score_history.py
web/templates/index.html
```

15 files present in live source but absent from the public tree:

```text
ghost_tesla_ai/forecast_quality_v2_api.py
ghost_tesla_ai/readiness_now_v2.py
ghost_tesla_ai/trip_quality_v3_api.py
ghost_tesla_ai/vehicle_sensors_v1.py
ghost_tesla_ai/winter_shared_score_v1.py
release-sidecars/evaluate.py
release-sidecars/evaluate_v2.py
release-sidecars/evaluate_v3.py
release-sidecars/evaluate_v31.py
release-sidecars/evaluate_v32.py
requirements.txt
web/templates/forecast_quality_v2.html
web/templates/ghost_vehicle_sensors.html
web/templates/trip_quality_v3.html
web/templates/trip_quality_v31.html
```

`requirements.txt` is tracked publicly already but not part of the 45-path Python/HTML baseline comparison, so this classification means **not compared against that filtered baseline**, rather than proven missing from GitHub. The other missing entries should be reconciled into portable, versioned package paths.

## Initial source and security checks

- All collected Python source and evaluators passed `compileall`.
- Evaluator v3.1 and v3.2 built-in `--self-test` passed.
- JavaScript in the extracted HTML templates passed `node --check`.
- Snapshot ZIP contained no telemetry DB files, binary model artifacts, `.env` or token files.
- Pattern scans found **no concrete VIN**, known private tailnet IP, obvious embedded credential literal, or `Bearer` token; this is **not** a complete security certification.
- Some sample coordinates appear inside the **pre-existing self-test fixture** for stable-location IDs. Never include real journey coordinates, addresses or per-user logs in public assets.

## Blocking portability and correctness issues

1. **Machine-specific paths.** New Flask APIs and shadow analyzers reference `/home/ghost/...` and/or `/var/lib/ghost-tesla-ai/...`. Fresh installs must use configurable, permission-safe defaults.
2. **Missing systemd contents.** The private inventory contains **20 unit names/statuses**, but does not include full service/timer definitions. Reconstruct using portable systemd templates, not assumptions about the developer's Linux username.
3. **All-trip semantics.** Trip quality should learn *every* completed journey, weekday or weekend, not use morning/afternoon labels as destination truth. Existing evaluation contexts remain diagnostic labels only.
4. **Expected overnight charging.** The v3.2 intervening-activity guard can wrongly exclude eligible forecasts when planned Level 1 charging finishes before departure. Fix before promoting quality metrics.
5. **Forecast source/meaning.** Distinguish historical predictions frozen before trips from post-hoc estimates; distinguish whether model assumed a charging schedule or unknown future action.
6. **New weather fields.** Verify fresh Open-Meteo hourly conditions, precipitation chance and wind after cache expiry. Tests with cached temperature alone are not proof of all-weather condition fields.
7. **Upgrade safety.** The public installer currently replaces application directories on upgrade. Preserve existing configuration/history and refuse to drop live-on-Pi modules or timers.
8. **Images.** Capture genuine current dashboard screenshots, review for secrets and private route details, and replace only images verified as actual running UI, not illustrations.

## Required validation before v1.0 tag

- Merge vetted live source, including newer sidecars, into this draft PR; preserve historical public changes on conflicts.
- Prove a fresh Raspberry Pi 5/Debian 64-bit one-command install can configure source credentials, deploy every unit, initialize DB and open all three dashboards.
- Prove an upgrade from v0.8.x preserves all model artifacts, telemetry history, service settings and shadow evidence.
- Verify specific page/API routes and automated evaluator freshness across reboot.
- Perform a full secrets scan of staged Git changes and public screenshots.
- Leave PR in draft until all checks pass. Publish **no GitHub release or major tag** before first-install acceptance.

The private snapshot must not be attached to issues, commits, or release assets.
