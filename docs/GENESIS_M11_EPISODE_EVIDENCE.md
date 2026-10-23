# GENESIS M11 — Episode-balanced, same-event thermal challenge

**Status:** Research-only extension. Existing M9 truth-watch and M10 challenger artifacts remain fixed and unchanged. No model deployment, automatic experiments or Hive protocol changes.

## Motivation

The M10 experimental ambient-relaxation model was frozen with observed historical coefficients:

- 60 minutes: alpha = 0.02981, historical challenger MAE 1.93°F versus 2.04°F for persistence.
- 180 minutes: alpha = 0.06271, historical challenger MAE 3.95°F versus 4.36°F for persistence.

Both historical comparisons were labeled `PAST_HOLDOUT_NOT_CONVINCING`. At initial freeze, no later forecasts had resolved. M11 must not invent future accuracy.

Thousands of forecasts can be generated during a single vehicle episode. A row-weighted average could allow one long parked/charging session to overwhelm several shorter events. Day coverage alone does not address this.

## M11 research method

The new `genesis/episode_challenge.py` reader:

1. Validates the fixed M9 and M10 artifacts; uses only GHOST's local read-only SQLite source.
2. Applies the M10 trial's frozen forecast-ID and clock-time boundary.
3. Requires all three predictions to be scored against the **same recorded future battery temperature**: production GHOST, frozen ambient-relaxation challenger reconstructed from starting pack/ambient temperature, and starting-temperature persistence.
4. Matches each forecast by its **source prediction timestamp** to at most one vehicle event from `vehicle_events`: drive, charge, park, sleep, cold-soak or precondition. If overlapping event intervals exist, picks the latest starting matching event, then its latest ID. Never returns the ID or event times.
5. First computes the mean absolute error **within each event**, then averages those event means equally by model generation/horizon/event category. One event counts once regardless of forecast frequency.
6. Reports matched forecasts, forecasts with no matching inferred event, and incomplete matched forecasts. Missing context is never treated as accurate evidence.
7. Marks a directional triage signal only with at least **five inferred events, three UTC days, and 100 matched forecasts** in the same model/horizon/event-type group. These are bounded heuristics, not statistical independence or causal findings.
8. Refuses more than 200,000 post-freeze candidate forecast rows or 6,000 resulting inferred event groups without an operator resource review.

The new read-only API route is `GET /api/genesis/episode-challenge`. GENESIS Investigations includes an **Episode-Balanced Research** panel showing real coverage and compared errors. No write route, new timer, or training work is created.

## Scientific limitations

The event labels are **GHOST-inferred**, may overlap, and can be regenerated or revised by the event engine. They are not externally verified, independently sampled trip outcomes. Assigning based on forecast-source time also does not mean the vehicle remained in that regime throughout a 60- or 180-minute forecast horizon.

Future GHOST forecast-source readings are stored in SQLite rather than cryptographically attested at prediction creation. This is research evidence, not a verified real-time adversarial-proof prediction ledger. There are no signed artifacts or approved production model changes.

## Deployment safeguards

The reviewed GENESIS-only staging script tests all `test_genesis*.py` regression files, changes only the isolated GENESIS viewer on localhost:8767, and verifies the read-only APIs. The existing M9 JSON, M10 JSON, historical research records, GHOST Classic, telemetry collector, timers, and Hive contribution consent remain untouched.

## Next development

- Check real post-freeze event coverage and query/resource cost on the Pi.
- Validate event reconstruction consistency across multiple refreshes and identify events revised after scoring.
- Introduce a separately permissioned, source-time research-prediction commitment ledger before trusting immutable challenger forecasts.
- Calculate uncertainty from genuinely independent and non-overlapping sessions, then decide whether a candidate merits new research.
- Build the bounded autonomous research runner and authenticated one-app integration only after resource and safety validation.
