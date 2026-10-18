# GENESIS M4 — Prediction Truth Lab (research-only)

## Why this milestone exists

The GHOST Hive v1.2 owner installation reported 17,742 resolved battery
temperature forecasts within the last 7 days, with 39.6% within ±2°F and a
4.45°F mean absolute error. The overlapping last 30 days reported 53,256
temperature forecasts, 55.7% within ±2°F and a 3.01°F MAE.

**Overlapping windows do not establish drift.** We need disjoint windows,
per-model/per-horizon evidence, consistent model generations, real sample counts
and explicit cautions, without changing live Classic GHOST.

## Implemented on the GENESIS feature branch

- New research-only `genesis.prediction_truth` reader uses SQLite URI
  `mode=ro` plus `PRAGMA query_only`. It never creates a source DB.
- New GET-only `/api/genesis/prediction-quality` endpoint on the isolated
  GENESIS viewer (or authenticated integrated GENESIS blueprint).
- Model Competition Lab now includes a lazily loaded *Prediction Truth Lab*;
  the query occurs when the Models panel is opened, no more than once every
  five minutes while the panel is revisited.
- True rolling recent 7 days versus the **previous** disjoint 7 days,
  using the resolved outcome timestamps.
- Aggregate only: counts, actual observed temperature MAE in Fahrenheit,
  hit rate within ±2°F, and groups by model name and horizon.
- A heuristic attention flag requires at least 100 scored outcomes in each
  period **and the same single generation in both windows**. Generation changes
  or mixed generations suppress the comparison.
- Extreme nonnegative errors remain counted; the system does not silently
  suppress the bad predictions that should be investigated.
- Output has no VIN, user identity, GPS, raw sample, route, precise event time
  or vehicle command. No changes to HIVE consent or public JSON.

## Interpretation

`WORSENING_TO_INVESTIGATE` means the recent period had at least 0.5°F higher
mean absolute error **and** at least 5 percentage points less within ±2°F;
`IMPROVING_TO_INVESTIGATE` means the reverse. These are convenient research
triage flags, not statistical tests or causal findings.

Forecasts may be strongly correlated, and the operating mix, weather,
battery-heater state and composition of models can change. Resolution time
is not necessarily the exact time the predicted condition was observed.

Nothing on this endpoint proves true prospective accuracy, directly compares
candidate models against an incumbent on matched observations, or qualifies
automatic promotion.

## Next scientific milestones

1. Inspect the actual model and horizon-specific 7/7-day patterns from Ghost,
   including any generations that changed.
2. Add local-only segmented error analysis by independent available operating
   evidence, coverage counts and cause/quality caveats.
3. Align experimental GENESIS predictions with *exactly the same evaluation
   events* as a frozen incumbent or persistence baseline to avoid comparing
   different samples.
4. Track multiple prospective periods, drift/calibration and independent
   review before describing an improvement as verified.
5. Consider a separately consented HIVE evaluation protocol only after the
   local evidence and privacy review are mature.

Do not modify the original Home dashboard or silently expand existing HIVE
consent. Do not run the experimental research engine automatically.
