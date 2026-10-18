# GENESIS M8 — manually frozen future-outcome watch

Status: research-only experimental milestone. Do not change production model selection from this output.

## The evidence problem it addresses

October 18 M7 audit showed every main temperature model family with enough recent paired observations losing to the simple no-change battery-temperature baseline. A historical paired loss is important, but it does not prove that future model forecasts will still lose. We need to register a future evidence boundary BEFORE collecting new outcomes.

## What M8 actually does

- A NORMAL USER explicitly runs `genesis.cli truth-watch-freeze` from the isolated GENESIS checkout.
- The module creates a *new* immutable-by-interface `prospective-truth-watch.json` file inside the private 0700 GENESIS state directory, mode 0600. It refuses to overwrite an existing watch and stores no raw GPS, route, VIN, telemetry records or credentials.
- The freeze records source path fingerprint, existing maximum prediction ledger ID, a wall-clock/source timestamp watermark and one observed generation per scored pack-temperature model/horizon. Model generations are version-locked; artifact-byte immutability is **not** guaranteed.
- GET-only status checks score resolved *new* forecasts whose audit IDs AND forecast/target timestamps are after the frozen boundary, and which resolved after the freeze. Pre-freeze forecasts that resolve later are excluded.
- Each scored production model prediction is compared with a persistence prediction using the EXACT same future actual temperature and initial source pack temperature. Results are grouped by model/horizon/generation, with sample coverage and explicit missing results.
- Frozen model generations that do not appear get null values and `AWAITING_FUTURE_EVIDENCE`, never misleading zero MAE. New generations are counted as excluded.
- Reads of the production data are `SQLite mode=ro` and `PRAGMA query_only`. An explicit upper bound rejects more than 200,000 qualifying post-freeze predictions without returning truncated evidence.
- No further writes to the watch on checks; no autonomous scheduling, retraining, promotion, Hive transfer or Tesla control.

## Existing M3 candidate distinction

GENESIS M3 already has a separate AFFINE_THERMAL manual candidate freeze with a different episode-based evidence ledger. M8 does NOT replace it, does NOT train any challenger and does NOT establish a contemporaneous candidate-versus-incumbent comparison yet. The next scientific phase must freeze a challenger alongside incumbent predictions on the same future events, with stronger ingestion-time provenance and independent episode scores.

## CLI (after staging the new GENESIS code)

```bash
cd "$HOME/genesis-product/current"
PY=/opt/ghost-tesla-ai/venv/bin/python
SOURCE=/var/lib/ghost-tesla-ai/ghost_ai.sqlite3
STATE="$HOME/genesis-product/state/prospective-truth-watch.json"

# One time, opt-in research initialization. Do not run until ready to start:
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$STATE" truth-watch-freeze

# Check from time to time; no new files, network calls, or source modifications:
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$STATE" truth-watch-check
```

The GENESIS read-only browser API route is `/api/genesis/prospective-watch`. The Investigations tab shows its current status; it cannot start a freeze. Before a manual freeze it reports `NOT_FROZEN`. Immediately afterward it should report `AWAITING_FUTURE_EVIDENCE`. Wait until new forecasts have been generated AND actually scored before expecting results.

## Required future development

1. Observe actual post-freeze model-vs-persistence measurements across weather/charging regimes.
2. Register candidate forecasts and incumbent forecasts at the same prediction event. Do not compare unlike periods, targets or ground truth.
3. Improve provenance by recording trusted ingestion-time anchors; a source timestamp can be backfilled.
4. Evaluate by independent trip/park/charge episodes and holdout spans, not raw correlated prediction row counts alone.
5. Only then consider a separately audited bounded automatic research scheduler and signed experiment artifacts. Model promotion remains explicitly prohibited without a separate release review.
