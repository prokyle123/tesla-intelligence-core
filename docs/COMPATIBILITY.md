# Compatibility

Tesla Intelligence Core is not intentionally locked to one Tesla model, but development/testing has primarily centered on **Model 3 telemetry**.

Different Tesla models, years and telemetry providers can expose different fields. Some dashboard features depend on specific battery/thermal signals being available.

## Current public source paths

| Source | Status | Notes |
|---|---|---|
| Tessie API | Supported by installer | Live telemetry + optional historical backfill |
| TeslaMate MQTT | Supported by installer | Requires an existing TeslaMate MQTT broker |

## Vehicle compatibility

Rather than claim unsupported coverage, this project uses community field reports.

If you test another model, please report:
- Tesla model;
- model year;
- telemetry source;
- SOC works? yes/no;
- outside/cabin temp works? yes/no;
- pack temp works? yes/no;
- module min/max works? yes/no;
- charging state/power works? yes/no;
- drive event detection works? yes/no;
- departure learning works? yes/no.

Do not post a full VIN publicly.

## Feature degradation

If a vehicle/source does not expose a signal, the related feature should degrade gracefully or show missing/thin evidence.

Examples:
- no module temperatures → module-spread analysis cannot be trusted;
- no pack temperature → thermal readiness becomes limited;
- limited history → schedule/cold-soak confidence remains thin.

Compatibility fixes are welcome through issues and pull requests.
