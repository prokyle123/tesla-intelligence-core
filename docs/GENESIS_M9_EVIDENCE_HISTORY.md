# GENESIS M9 — prospective evidence across multiple days

Status: development branch; install only into the isolated GENESIS viewer after offline regression tests.

## What changed

1. **Multi-day prospective quality gate.** The M8 future-outcome watch now requires both at least 100 complete, same-event production-vs-persistence comparisons *and* evidence scored across at least three distinct UTC resolution days before reporting a directional assessment. A single day's rapid forecasts can never be labeled a validated future model advantage. Three days do NOT mean three statistically independent trips; the API and UI say that explicitly.
2. **Stable missing evidence.** Every frozen model/horizon/generation contains an `evidence_days` integer and the existing null-valued error fields when no future scores exist. Existing M8 freeze files are not rewritten or invalidated.
3. **Private research-history ledger.** A manual CLI command, not the web API or a timer, may record the current post-freeze aggregate result in a private 0600 SQLite database beneath GENESIS's 0700 state folder. Only approved model names, horizon, generation, sample counts, UTC evidence-day coverage and model/persistence error summaries are saved. No VIN, location, trip history, Tesla credentials, source-row identifiers, exact prediction times, model artifacts, vehicle actions or Hive uploads are included.
4. **Deduplication and bound.** Re-running an unchanged manual record operation stores nothing new. A maximum of 512 aggregate snapshots per frozen watch returns a capacity-review state instead of silently deleting history. Read-only history retrieval never creates a file.
5. **GENESIS dashboard.** Investigations shows days of evidence per model and up to 10 recent manually saved aggregate snapshots. The web service has no endpoint to freeze or record research.

## Install and begin a watch

Install the reviewed GENESIS feature branch with `scripts/genesis_preview_upgrade.sh`. It verifies all research endpoints and leaves Classic GHOST, Hive consent and production models unchanged.

From the isolated GENESIS checkout, set the explicit source, watch and history paths:

```bash
cd "$HOME/genesis-product/current"
PY=/opt/ghost-tesla-ai/venv/bin/python
SOURCE=/var/lib/ghost-tesla-ai/ghost_ai.sqlite3
WATCH="$HOME/genesis-product/state/prospective-truth-watch.json"
HISTORY="$HOME/genesis-product/state/prospective-truth-history.sqlite3"

# Once when ready to start collecting future scored predictions.
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" truth-watch-freeze

# Read current evaluation (no writes), now or on later days.
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" truth-watch-check

# After new resolved forecasts exist, manually record aggregate evidence.
"$PY" -m genesis.cli --source-db "$SOURCE" --truth-watch-file "$WATCH" \
 --truth-history-db "$HISTORY" truth-watch-record

# Review cumulative saved summaries (read-only).
"$PY" -m genesis.cli --truth-watch-file "$WATCH" \
 --truth-history-db "$HISTORY" truth-watch-history
```

**Do not remove or recreate an existing freeze file.** It defines a fixed experiment. The M9 reader is compatible with valid M8 freeze files and older stored history is preserved.

## Still not implemented

- Verified arrival/ingestion provenance: source prediction timestamps can be backfilled.
- Independent trip/charge/park episode evaluation: distinct UTC days reduce concentration, but correlated row counts remain.
- Frozen experimental challenger versus the active incumbent on identical future events.
- Automatic resource-limited research scheduling, signed model artifacts or promotion.
- Expanded Hive consent or network research sharing.

These are the next research gates, not features to imply are already running.
