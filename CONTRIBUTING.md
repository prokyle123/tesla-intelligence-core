# Contributing

Contributions, compatibility reports and field observations are welcome.

Tesla Intelligence Core benefits especially from real-world diversity: different Tesla models, climates, charging setups and telemetry sources.

## Useful contributions

- compatibility reports from other Tesla models;
- Tessie / TeslaMate field-normalization fixes;
- cold-climate thermal behavior observations;
- charging-behavior edge cases;
- Raspberry Pi performance improvements;
- prediction / Truth Lab improvements;
- dashboard usability work;
- installer and documentation improvements;
- tests based on synthetic or redacted telemetry.

## Before opening an issue

Please search existing issues first.

For bugs, include:
- project version;
- Raspberry Pi / host model;
- OS;
- telemetry source;
- relevant service status;
- redacted log excerpt;
- expected behavior;
- actual behavior.

Do **not** include Tessie tokens, MQTT passwords, full VINs, exact coordinates/addresses, or raw private telemetry dumps.

## Compatibility reports

If the project works (or partly works) on a Tesla model not yet documented, include:
- model / model year;
- Tessie or TeslaMate;
- which dashboard signals populate;
- which signals are missing;
- whether pack/module temperature fields are available;
- whether departure/event detection works.

See [Compatibility](docs/COMPATIBILITY.md).

## Pull requests

Before opening a PR:

```bash
python3 -m compileall -q ghost_tesla_ai
```

If changing installer/runtime behavior, explain:
- whether existing `/etc/ghost-tesla-ai` config is preserved;
- whether `/var/lib/ghost-tesla-ai` data/models are preserved;
- whether systemd unit behavior changes.

## Scope

The project is currently intentionally **read-only**.

Vehicle-control features are out of scope unless the project direction explicitly changes.

## Public Git history and release workflow

The public `main` branch is the release record, **not** a scratchpad.

1. Start a focused branch from current `main` (for example, `fix/pack-forecast` or `feature/dashboard-chart`).
2. Commit freely while experimenting **on the branch**. Keep private test data, tokens, VINs, private IPs, and live route/location records out of Git entirely.
3. Open a pull request against `main`. The smoke workflow runs on PRs and on `main` pushes, not on every development-branch push.
4. Run tests and review changed files and screenshots. For companion emulator screenshots, download the Actions artifact, redact/review it, and add selected images to the same PR. CI never pushes screenshots to `main` automatically.
5. Choose **Squash and merge** for the PR so `main` receives one descriptive commit per completed change. Do not use a normal merge or rebase merge for routine work.
6. Tag and release only a tested `main` commit. Keep installer configuration and model history separate from the repository.

Repository maintainers should configure GitHub Settings > Rules > Rulesets (or branch protection) to require a pull request and passing `source-sanity` checks on `main`, and use Settings > General > Pull Requests to retain squash merging while disabling merge-commit/rebase methods. These settings must be applied in GitHub; this document does **not** enforce them.

**Existing published commits:** do not force-push or rewrite `main` merely to hide an untidy development history. Old commit links, signed tags, release ancestry, forks, and clones can be disrupted, and previously public content may remain accessible elsewhere. For real credential exposure, rotate/revoke first and handle history cleanup as a separately reviewed incident.

The automated public-source check detects common textual exposures, **not** secrets of every format or sensitive details inside screenshots and binary files. Continue human review.
