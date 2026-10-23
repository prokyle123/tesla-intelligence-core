# GHOST HIVE v1.3 — First-contributor Fleet Intelligence display

**Release scope:** A private dashboard presentation fix. It does NOT create new enrollment, broaden Hive sharing, upload any new vehicle data, or relax public privacy thresholds.

## Why the page looked empty with a real first reporter

The Hive coordinator already returns an overall `reporting_nodes` count that **can truthfully be one**. The private Hive template previously treated the month-by-month chart as empty until a monthly cohort reached 10 reporting installations. This conflated an existing overall enrollment with the separately protected monthly release data.

### Implemented

- The private **Contributing Vehicles** panel now shows the real, coordinator-confirmed overall count, including **1**, whenever qualified monthly cohorts are unavailable. A discrete count and enrollment progress bar are labeled **overall enrollment only** — never a real monthly trend.
- If monthly cohort data becomes large enough and passes the existing validator, it still uses the original real per-month SVG graph.
- The 7-day/30-day control no longer obscures the overall total; daily contributor history is still explicitly unavailable, rather than invented.
- **Contributing Regions** now says its KPI counts **qualified public groups**, not owner-selected regions. The count can remain **0** even if the owner has voluntarily selected a region.
- The private region panel can show **Your selected broad region**, in a clearly marked owner-only row. This is a local choice, **not proof of a qualified public regional group** or evidence of the vehicle's exact route.
- No public page exports the owner's region below the existing **10 same-UTC-month reporting-installation** threshold. The private display still uses consented region categories only; no GPS, city or country is inferred from local drives.
- Country rankings and actual driver route hotspots remain unavailable. They require a *different explicitly reviewed and consented protocol*; the current six-field report does not include them.

## Important two-site distinction

- **On Ghost**: the owner-only `http://127.0.0.1:8766/hive` page fetches `/api/hive/local` and can display real local contribution/enrollment status immediately, provided its loopback coordinator responds.
- **Public Pages preview**: `docs/hive/network.json` is a sanitized placeholder until an operator publishes a **real validated HTTPS feed**. Updating local code or refreshing a private local static preview does not automatically update GitHub Pages. The public page must never display a hard-coded `1` to simulate a network member.

## Safe install

Run `bash scripts/hive_v13_fleet_deploy.sh check` first, then the explicit `install` mode when preflight succeeds. The reviewed exact predecessor Hive v1.2 HTML Git blob is allowlisted in `scripts/ghost_hive_update.py`; unknown live edits stop the upgrade.

The installer backs up Hive-owned files, restarts only `ghost-tesla-ai-web.service`, checks live API + HTML presentation, refreshes the safe local public preview, and verifies SHA-256 of the original Home template and server are unchanged. Classic models, collector, GENESIS viewer, M9/M10 freezes, Hive consent and hourly timers are not modified. A detected post-apply failure triggers checksum-bound Hive-only rollback.

## Ecosystem next gates

1. Finish first-install onboarding, tested upgrade and rollback paths for Classic + GENESIS + opt-in Hive as a coherent product, preserving isolation.
2. Publish only the sanitized live Hive `network.json` to an approved HTTPS origin and verify Pages freshness/status. Never expose the loopback coordinator directly.
3. Implement hardened independent multi-node coordinator deployment: TLS termination, per-installation credentials, replay/rate limiting, backups, revocation and abuse controls.
4. Design separately consented cohort protocol v2 for *optional country or macro-region statistics* after a privacy threat model and 10+ reporting-installation release gate. Exact routes, workplaces, homes, GPS traces and ranking individual drivers remain out of scope for public publication.
5. Add honest fleet-wide model validation and new independent trials across installations. Do not claim federated AI training from the existing monthly MAE summaries; independent candidate-model and federated-learning workflows remain future.
6. Preserve Classic GHOST readiness and its installed models; continue validated GENESIS research separately, with no automatic production promotion.
