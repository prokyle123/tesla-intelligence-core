# GENESIS M6–M7: Research intelligence progression

Status: development branch; no Classic GHOST or Hive protocol changes.

## Motivation

On October 18, the Ghost M5 diagnostic found pack temperature MAE 4.48°F and 39.3% within ±2°F in the recent seven days, versus 2.22°F and 65.4% within ±2°F in the prior disjoint week. Both main models increasingly overpredict temperature. A scientific investigation must distinguish forecast error, source conditions, model-generation changes and model superiority over a simple baseline.

## Implemented M6: Source-condition evidence

- Read-only SQLite aggregation of actual resolved temperature predictions joined to the original source telemetry.
- Ambient bands: at/below 32°F; 32–50°F; 50–68°F; above 68°F; unknown.
- Separate reported vehicle state and explicit heater ON/OFF/unknown.
- Separate recent and previous seven-day outcome-resolution periods.
- Reject mixed-vehicle databases and preserve unknown/missing context evidence.
- Generation-consistent heuristic comparison with a minimum of 100 resolved forecasts in each period.
- Up to five fixed, evidence-led research proposals, always PROPOSED_NOT_EXECUTED and requiring operator review.
- No exact timestamps, source IDs, VIN, raw telemetry, trips or locations in the API output.

Source conditions are observations at forecast creation, not necessarily over the full prediction horizon. Associations are not causal proof.

## Implemented M7: Same-outcome model versus persistence

For each resolved model prediction with complete starting and actual pack temperature evidence, the production model and simple no-change persistence baseline are compared against exactly the SAME actual future temperature, grouped by model name, horizon, generation and reporting week.

Models historically winning or losing by at least 0.5°F are labeled only with at least 100 paired recent outcomes. This is observational; closely spaced forecasts can be correlated, and these results are not independent prospective validation.

## UI and deployment

The GENESIS Model Competition Lab displays M6 context and M7 matched baseline. The Hypothesis Architect Investigations tab surfaces proposed next research questions. All use GET-only endpoints in the isolated, loopback-restricted GENESIS preview.

The existing GENESIS-only upgrade script tests and stages versioned files, then verifies prediction-quality, thermal-context and paired-baseline endpoints. It does not modify the Classic Home dashboard, production model selection, Hive consent, vehicle commands, timers or coordinator.

## Next milestones

1. Run real M6/M7 evidence on the Ghost Pi and inspect model-generation comparability, source coverage and compute cost.
2. Investigate cold-weather thermal bias with honest matched regime/horizon comparisons.
3. Freeze prospective candidate evaluations against BOTH persistence and the actual incumbent on newly arriving evidence.
4. Add a bounded, separately approved GENESIS research runner with resource caps, logs, pause/rollback and strict allowlisted recipes; do not enable an autonomous scheduler silently.
5. Integrate authenticated research access into one GHOST application, preserving its production Home and data isolation.
6. Only after local validation, expand the Hive fleet research protocol with fresh opt-in consent, independent enrollment and security review.
