# Contributing

Issues, field reports and pull requests are welcome.

Useful contributions include:

- compatibility reports from other Tesla models;
- Tessie/TeslaMate field normalization fixes;
- thermal behavior observations from colder climates;
- Pi performance improvements;
- prediction/truth-audit improvements;
- dashboard usability work;
- tests that use synthetic/redacted telemetry.

Please do not attach raw telemetry containing VINs, exact locations, credentials or other private vehicle data to public issues.

Before opening a PR:

```bash
python3 -m compileall -q ghost_tesla_ai
```

Keep vehicle control out of scope unless the project direction explicitly changes; GHOST is currently designed as read-only observation/prediction software.
