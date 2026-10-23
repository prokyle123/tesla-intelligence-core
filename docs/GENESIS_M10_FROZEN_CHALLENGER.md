# GENESIS M10 — Frozen, same-outcome thermal challenger

**Status:** GENESIS research-only development. Classic GHOST, its active model selectors, the existing M9 freeze and consented Hive reports remain unchanged.

## Problem being tested

The October 18 M7 audit on Ghost showed that its major scored battery-temperature models often lost to a persistence predictor (assume the pack temperature remains unchanged). M8/M9 already froze existing model generations for future GHOST-versus-persistence evaluation, and that private M9 watch is active.

M10 tests an actual competing model while **preserving the existing M9 watch**.

## Pre-freeze recipe

`genesis.frozen_challenger` implements a fixed deterministic physical research formula:

```text
predicted_pack_temp_c = source_pack_temp_c +
  alpha_h * (source_outside_temp_c - source_pack_temp_c)
```

The relaxation coefficient `alpha_h` is estimated separately for each eligible forecast horizon using scored, observed battery-temperature outcomes **from before the challenger freeze**. It is constrained to [0,1] and saved to five decimal places.

- Training: the older 14 days of a 21-day pre-freeze period.
- Historic holdout: the seven immediately preceding days.
- At least 120 training examples and 60 holdout examples spanning 3 UTC days for each horizon, plus nondegenerate ambient differences.
- The historic holdout is reported as exploratory evidence, not untouched validation.
- At most 150,000 pre-freeze resolved temperature forecasts are examined; excess requires review.
- Horizons with inadequate observed evidence are excluded. No placeholder coefficients or invented results.

The output is a new, exclusive-creation 0600 research artifact under the existing private GENESIS state directory. It records the original M9 watch hash, production source path digest, its own later forecast/record-ID watermark, frozen alpha per trained horizon, and historical aggregate counts. The artifact is protected by an integrity digest against accidental modifications (not a cryptographic signer).

## Future three-way evaluation

A manual GET or CLI check groups **only later-created and later-resolved production forecasts**. For each eligible forecast, the exact same recorded future temperature is used to evaluate:

1. Existing GHOST model prediction recorded at the time,
2. Persistence from the recorded source pack temperature,
3. Frozen ambient-relaxation challenger reconstructed from recorded source pack/ambient and frozen `alpha_h`.

We explicitly exclude generations that changed since the original M9 freeze. Horizons with insufficient training are reported separately, not mislabeled generation drift. Missing ambient/source/future truth reduces coverage and never becomes a zero-error result. A challenger needs at least 100 matched scored outcomes over 3 UTC resolution days before a directional research assessment is shown.

**Critical limitation:** This is a precommitted formula evaluated on future GHOST scoring events; challenger outputs are reconstructed later from the stored source snapshot. We do not yet have proof that every historical source snapshot was immutable at prediction time, nor independent arrival-time attestations or independent trip/charging episodes. It is a research trial, not a certified real-time forecaster.

## Operator-controlled commands

After upgrading the isolated GENESIS viewer, enter the existing staged research checkout.

```bash
cd "$HOME/genesis-product/current"
PY=/opt/ghost-tesla-ai/venv/bin/python
SOURCE=/var/lib/ghost-tesla-ai/ghost_ai.sqlite3
WATCH="$HOME/genesis-product/state/prospective-truth-watch.json"
CANDIDATE="$HOME/genesis-product/state/prospective-challenger.json"

# Check the already-frozen M9 watch (read-only).
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" truth-watch-check

# One-time, explicit M10 challenger training/freeze. Refuses overwrite.
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" --challenger-file "$CANDIDATE" challenger-freeze

# Later: read-only M10 challenger vs incumbent vs persistence check.
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" --challenger-file "$CANDIDATE" challenger-check
```

The public HTTP endpoint is **not** used. Only the loopback GENESIS research viewer serves `GET /api/genesis/challenger`; it does not expose any create, freeze, execution, model-control or write route.

## Next milestones

- Verify actual on-Pi M10 historical training coverage, coefficient sanity, CPU/database costs, future scored evidence and UI.
- Preserve the old M9 trial and periodic manual evidence recording.
- Track matched outcomes across independently inferred trips/parked sessions, not merely UTC days, before claiming reliable skill.
- Replace reconstructed challenger evidence with a separate, offline-only *prediction-time commitment ledger* that captures initial feature snapshots and signed recipe digests without changing the GHOST production pipeline.
- Only after demonstrable reproducible improvements, design resource-bounded research scheduling and one-app integration. Keep production model promotion and HIVE data permissions separate.
