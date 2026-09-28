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
