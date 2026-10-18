# GHOST GENESIS — v2 architecture and safety plan

**Status:** Experimental, first local milestone. This is NOT a production v2.0 release.

GENESIS lives in the existing Tesla Intelligence Core repository but runs as
an optional, independently developed research module. GHOST Classic continues
to own existing readiness, trip learning, neural predictions, and its dashboard.

## Hard safety boundaries

- No vehicle controls, charge commands, Tessie API writes, new telemetry polling,
  automatic Tesla wakeups, production model promotion, or generated-code execution.
- No autonomous research service or timer yet. Research requires an explicit
  local command while we validate CPU, memory and storage use on the Pi.
- Production SQLite is opened read-only, with a strictly allowlisted set of
  numeric telemetry columns. No raw JSON, VIN, car IDs, routes, coordinates,
  address, location, or personal trip records are loaded by the research engine.
- The research ledger is an independent private SQLite database at
  /var/lib/ghost-tesla-ai/genesis/research.sqlite3 by default. The source
  database path cannot be used as the research write target.
- Multiple car IDs in the source database cause a safe refusal, rather than
  accidental mixing of unrelated vehicle histories.
- The Classic dashboard is not redesigned. New /genesis and
  /api/genesis/overview endpoints are registered ONLY if the explicit
  GHOST_GENESIS_ENABLED=true flag is set in GHOST configuration.
- These read-only endpoints inherit GHOST's existing LAN/tailnet boundary,
  which must not be mistaken for public authentication.
- The Hivemind contains no network transport. Even requesting contribution
  mode does not enable uploads, telemetry sharing, or global model downloads.

## What the first research engine actually does

GENESIS enumerates approved numerical feature/target pairs, derives candidate
simple models from historical data and evaluates each on a *later* time window
with a temporal embargo and minimum evidence thresholds. It requires positive
holdout improvement in both test halves.

Results are marked SHADOW or REJECTED. A SHADOW result means only
"an experimental association survived these local tests," NOT a newly
discovered causal mechanism, a production accuracy improvement, or a
fleet-validated finding.

Current time-series methods remain deliberately modest and will need stronger
controls for temporal autocorrelation, drift, class imbalance, and rare regimes
before accepting any model into production.

## Safe local testing

Clone the *feature/genesis-v2-foundation* branch to a disposable test machine
and supply synthetic data or an approved local test copy (never upload a real
vehicle database to GitHub):

~~~bash
python3 -m unittest discover -s tests -p 'test_genesis*.py' -v
python3 -m genesis.cli --source-db /path/to/test.sqlite3 --research-db /path/to/private-research.sqlite3 run-once
python3 -m genesis.cli --research-db /path/to/private-research.sqlite3 status
python3 -m genesis.cli hivemind-status
~~~

No scheduled job is installed by those commands. A research cycle does not
modify production DB data, existing neural artifacts or GHOST services.

After future review and a separate backup, enabling the optional UI on Ghost
would mean adding GHOST_GENESIS_ENABLED=true to the *existing private*
/etc/ghost-tesla-ai/ghost.env, then restarting only the GHOST web service.
Research runs remain manual and disabled-by-default regardless of that setting.
**Do not deploy this prototype to the running Pi until the audit and rollback
steps are completed.**

## Privacy-first Hivemind architecture

The Hivemind in this milestone is an **offline synthetic-only harness**,
NOT a working federated learning system. Its illustrative minimum cohort
threshold of 25 is not an anonymity guarantee.

Before any real cross-owner learning:

1. Consent must be explicit, separate, reversible for future contribution
   and OFF by default. Receive-only and local-only modes are required.
2. Secure aggregation must prevent the coordinator from seeing individual
   updates. Implement differential privacy with a real privacy accountant,
   clipped updates and independent membership-inference tests.
3. Protect against small/coerced cohorts, Sybil participants, repeated/differenced
   aggregate queries, poisoning and adversarial global-model releases.
4. Do not send VIN, GPS, routes, personal schedules, timestamps, full sensor
   series, model fingerprints or device IDs to fleet services.
5. Network metadata is still visible to ordinary servers even if payloads
   are encrypted. Minimize logs, avoid tracking cookies/pixels, and evaluate
   opt-in network relays and short-lived credentials.
6. Public statistics require large privacy-reviewed cohorts, versioned
   methods and delayed fixed publication windows. Until then display
   "not available" rather than invented participants or accuracy scores.
7. Global models must be signed and evaluated in local shadow mode;
   owners may reject updates. Global models never overwrite personal ones.

## Roadmap: autonomous research and global fleet

- **M0, now:** bounded local hypothesis engine, strict read-only source,
  independent research ledger, separate dashboard, offline privacy gate,
  synthetic regression tests.
- **M1:** improved experiment replay, deduplication, holdout protocols,
  trustworthy evidence scores, CPU quotas, manual model comparisons.
- **M2:** structured hypothesis planner and experimental DSL, isolated
  execution sandbox, safe model artifact lineage, approved proposal workflow.
- **M3:** fully simulated multi-client learning, robust privacy threat model,
  secure aggregation and calibrated differential privacy verified before
  any actual sharing is enabled.
- **M4:** separate Hivemind coordinator and public Fleet Observatory with
  privacy-filtered aggregate accuracy, model generations and discoveries.
- **M5:** federated research missions with rollback, signed models, shadow
  evaluation, anti-poisoning and accountable governance.

**Deployment rule:** develop on feature branches, require passing safety
regressions, review diff and only squash-merge tested work. Never overwrite
the running Ghost install as an unreviewed experiment.


## Read-only Pi preflight — required before enabling GENESIS

Once this draft branch has been reviewed, run the following from a
*separate working checkout* of the repo on the Pi:

~~~bash
python3 scripts/genesis_host_preflight.py
~~~

The report shows architecture, available RAM and storage, read-only telemetry
row count, service states, Genesis flags and warnings. It deliberately omits
network addresses, vehicle identifiers, actual observations and secrets.
The preflight performs no writes or network calls. Copy only that JSON
summary back for an installation decision.

To try a synthetic fleet round without touching any production information:

~~~bash
python3 -m genesis.cli simulate-fleet --nodes 32 --rounds 30
~~~

This is explicitly a **simulation**, NOT secure aggregation or differential
privacy and not representative of real fleet accuracy.

## M1 retrospective research audit (read only)

The first live M0 run selected eight shadow pairs from 6,000 observations.
The new `audit-candidates` command checks **those frozen candidate names**
on up to 6,000 earlier, non-overlapping observations. It never writes research
history or GHOST production state and never promotes models.

Use the same local research database that contains the first run:

~~~bash
python3 -m genesis.cli \
  --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 \
  --research-db /tmp/genesis-first-research.i4UGDw/research.sqlite3 \
  audit-candidates --max-rows 12000 --recent-window 6000
~~~

The output lists bounded walk-forward fold errors, first-difference controls,
and availability of driving/charging/parked regime evidence. Any warning is
designed to keep an apparent relationship in research rather than production.

**Important:** This is historical repeatability, not independent future
confirmation. The first discovery was selected from the newest 6,000
observations; replaying older records cannot prove causal interpretation or
guarantee performance on future trips. Later M1 must freeze the experiment,
wait for genuinely new observations, and audit model drift without selecting
the outcome beforehand. The audit uses no personal timestamps, coordinates,
vehicle identifiers or raw sensor streams in its output.
