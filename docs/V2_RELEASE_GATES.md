# V2 release / installer acceptance gates

This is the blocking checklist for a **public major release**, not a statement of completion. The current integration branch is intentionally not a tagged release. No production Tesla credentials, addresses, routes, personal logs, SQLite data or model weights belong in Git history.

## Release gate: source completeness

- [ ] Reconcile the latest running /opt/ghost-tesla-ai source and the GitHub web templates. Confirm exact diffs, keep every existing feature and preserve upstream fixes.
- [ ] Package the separate /opt/ghost-intelligence application, V5 sensor evidence, V6.2 memory, V6.4.4a claim engine, V6.6 async commentary and watchdog as versioned portable source.
- [ ] Port voice/readiness panels and hourly alerts from the **current installed** dashboard, not old screenshots or incomplete patches.
- [ ] Remove developer-specific /home/ghost, Pi-specific tailnet addresses, SD-card device names and hardcoded paths. Use configuration and selected service user instead.
- [ ] Verify licensing/provenance of each redistributed code/model component. Do not commit 4B GGUF weights or llama-server binaries.

## Release gate: install and upgrade

- [ ] Core v1 functionality installs and runs with optional AI **disabled by default**.
- [ ] Optional intelligence prompts for explicit opt-in, validates RAM/architecture and model presence/download, and refuses unsafe configurations.
- [ ] Installs independently managed systemd units, correct ExecStart and permissions, and idempotent watchdog timers without hardcoded user paths.
- [ ] Dashboard displays a readable **AI unavailable / verified fallback** state when no model is installed; live readiness and alerts never depend on a network call to 4B.
- [ ] Upgrade from v1 and an existing development Pi preserves all source modules, dashboards, config, credentials, SQLite rows, learned models, timers and remote-access gateway. Stage/backup/compare before replacing any directory.
- [ ] Demonstrate clean uninstall/rollback of the optional intelligence while leaving core telemetry and neural models untouched.
- [ ] Test model-server timeout, 503/busy endpoint, high swap pressure, crashing model, stale Tesla data, failed briefing timer and no network.

## Release gate: correctness and learning claims

- [ ] Repeat full/withheld-evidence narration tests on multiple independent days and record real acceptance/fallback rates.
- [ ] Guard numbers, derived temperatures, baseline relationships, unsupported stability/trend assertions and HVAC/heater evidence.
- [ ] Keep Right Now readiness distinct from next-departure predictions.
- [ ] Don't publish thermal uncertainty ranges until independent calibration qualifies.
- [ ] Keep experimental V6.5.1 ambient model out of production: it did **not** beat the simple holdout comparator.
- [ ] Report numerical-model validation separately from text-model response acceptance. Memory retrieval is not automatic 4B fine-tuning.

## Release gate: security, portability and public publishing

- [ ] Run public file exposure scan, static checks, unit/fixture tests and current smoke CI.
- [ ] Test fresh install on Raspberry Pi OS/Debian 64-bit with a non-developer username and a non-/home/ghost path.
- [ ] Test real upgrade of a disposable clone/backup before touching a production installation.
- [ ] Check user-facing instructions, privacy notices, model provenance, Docker/WSL assumptions and API auth boundaries.
- [ ] Capture actual, privacy-reviewed latest dashboard screenshots.
- [ ] Require the release PR to pass CI and a human-checked install/rollback report **before** merging and tagging v2.0.
- [ ] Do not automatically deploy this branch to the operator's working Pi.

## Non-mutating reconciliation helper

Run from a checked-out version of this branch:

```bash
python3 scripts/v2_release_inventory.py
```

This inventories services and code-file hashes only. It neither copies code nor runs an installer. The developer should privately review any source snapshot before it is shared with another system or published.
