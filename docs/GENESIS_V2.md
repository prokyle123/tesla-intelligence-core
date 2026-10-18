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

## M1 evidence-coverage correction after first real Pi run

The first retrospective run checked 8 candidates against 6,000 older telemetry
records. Only 2 relationships met the simple historical fold rule, and zero
passed a prospective evaluation. Every pair reported only CHARGING-regime
coverage. This is a warning about sample composition, not evidence that the
car never drove.

An audit-quality correction adds UNKNOWN and CONFLICT categories rather than
treating missing speed/power readings as parked. It counts both raw and
10-minute-thinned observation coverage. Changes between sensor observations
are tested only across adjacent readings no more than 30 minutes apart, in
the same unambiguous regime. Jumping between unrelated trips can no longer
look like a meaningful physical delta.

Commands in a temporary checkout (read-only, no service changes):

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 coverage --max-rows 12000

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --research-db /tmp/genesis-first-research.i4UGDw/research.sqlite3 audit-candidates --max-rows 12000 --recent-window 6000

These only emit private counts and inference metadata; the source and ledger
remain unchanged. The coverage output must not be published as a fleet
metric. A historical association is neither a causal discovery nor proof
of real-time future forecasting accuracy.


## M1 distributed-history quality gate

The first live 12,000-row sample had 7,890 charging, 3,038 parked/other,
and 1,072 driving observations inferred from sensor data. Ten-minute thinning
retained 1,227 rows (10.22%). Low retention is not automatically an error,
but the sample may overrepresent long charging events.

The new "historical-coverage" command checks five nonoverlapping
chronological blocks spread across the local existing history, with
2,400 raw records per block (12,000 maximum). SQLite is opened strictly
read-only within one snapshot. No VIN, car ID, GPS, raw JSON, trip routes
or precise activity timestamps are loaded or returned.

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --research-db /tmp/genesis-first-research.i4UGDw/research.sqlite3 historical-coverage --blocks 5 --rows-per-block 2400

It lists per-era regime observations and paired-signal coverage for the
eight previously selected shadow candidates. This is a local evidence
diagnostic, not validation on unseen future trips. It does not train,
promote models, modify GHOST, or contact Hivemind.


## M2 Hypothesis Architect prototype (manual, locally self-directed)

The first hypothesis-planning loop is now implemented. GENESIS can inspect
five nonoverlapping historical blocks, automatically select from eleven
preapproved research questions, and train a basic contemporaneous linear
association model on the first three eras. It challenges each model on two
later eras, using the **same activity regime** and a constant baseline
trained only on the earlier observations.

Each trial is marked SHADOW_ASSOCIATION, CHALLENGE_FAILED or
INSUFFICIENT_EVIDENCE. It also has an explicit confounding caveat and a
next-experiment recommendation. The mission selector prioritizes resolving
a high rate of ambiguous simultaneous driving/charging signals; otherwise
it prioritizes evidence gaps, challenge of stronger candidates or failures.

**Limitations:** This is a rule-constrained local experiment planner, not
self-modifying AI, a future-time forecast, a proof of causality or a trusted
fleet discovery. The signals are contemporaneous, all recipes are vetted
and fixed in the source, and selection on historical data is exploratory.
Known thermodynamics/electrical relations are not novel discoveries. The
sample spacing is three minutes within one classification and does not yet
establish independent trip or charging episodes.

No background tasks, Tesla commands, new services, public fleet endpoints
or model promotion are added. Production is untouched.

Run from the isolated, reviewed checkout with a private output database,
specifying a suitable writable private directory:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --architect-db /home/ghost/genesis-lab/architect.sqlite3 architect-once --rows-per-block 2400

The default performs **no writes**. Add --save to explicitly write the
aggregate plans and results to this separate, local SQLite file.
The private ledger stores only research-plan metadata, not raw readings,
VIN, GPS or driving routes.

Read results later:

    python3 -m genesis.cli --architect-db /home/ghost/genesis-lab/architect.sqlite3 architect-status

The optional dedicated GENESIS dashboard includes an Architect mission panel,
but enabling a web route in the existing production web process requires a
separate reviewed deployment. At this stage the CLI works without installing
or restarting any production services.

Next planned features: episode-based grouping, well-calibrated baselines,
independent future outcomes after hypothesis freeze, drift/uncertainty,
signed candidate artifacts, safe competition against baseline production
models, and manual approval before any production promotion.


## M2 real follow-up missions: conflict forensics and parked +60m forecast

The initial five-era Architect run evaluated 11 preapproved recipes and
automatically selected the sensor-context conflict investigation. Three
recipes passed their retrospective historical challenge, eight failed.

The next **vetted** follow-up can be executed with the already saved
private Architect ledger in the temporary reviewed checkout:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --architect-db /home/ghost/genesis-lab/architect.sqlite3 mission-next --rows-per-block 2400

Only a preapproved mission type can be run; no saved mission string is
used as executable code, a dynamic import, or a network destination.
The RESOLVE_SENSOR_CONTEXT handler aggregates conflicting speed and
charger-power observations by historical era, by power-signal type, by
run-length bucket and by neighboring inferred state. A signal overlap
does NOT prove simultaneous physical charging and driving. Charger fields
may have stale samples, different semantics, or unsynchronized reporting.
All outputs are counts and qualitative next questions; no individual
records, addresses, IDs, coordinates or precise timestamps appear.

The next direct forecast experiment is:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 mission-thermal --rows-per-block 2400

This model takes current parked pack temperature and ambient temperature
and predicts pack temperature about one hour later. It first builds
observed parked episodes. Driving/charging observations, active indicated
pack heating and gaps greater than 15 minutes split episodes. Targets
must be within 10 minutes of the 60-minute horizon and within the same
episode. Training uses three chronological historical eras; the model
is challenged on two later eras and compared against a pack-temperature
persistence forecast. Minimum episode and anchor counts apply. A
nonlinear future ambient/weather curve is NOT supplied; this is a basic
one-hour relaxation model. Preconditioning and heater telemetry can be
incomplete. A historically repeatable trial remains experimental rather
than prospective confirmation.

Both mission commands are local and read-only. They do not write to the
production database, alter GHOST models, schedule research, control Tesla
hardware, upload to Hivemind, or claim causality. Private derived output
must not be treated as publishable fleet evidence.


## Full-history complete-episode thermal research (M2)

The first real 60-minute parked thermal experiment had 38 training
episodes but only one and four qualifying later-era episodes. It was
correctly labeled insufficient evidence, not an inaccurate model.

The new command reads up to 100,000 recent existing numeric telemetry
records from read-only SQLite, streaming parked episodes rather than
taking artificial disjoint row windows:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 mission-thermal-full --max-scan 100000

The maximum supported scan is 120,000 observations. Each episode holds
at most 4,800 observations; oversized episodes are excluded rather than
cut into artificial independent episodes. Inferred parking ends when
activity changes, an active pack-heater or precondition signal appears,
the timestamp goes backwards or the telemetry gap exceeds 15 minutes.
Hourly prediction targets must belong to the same contiguous episode.

Complete episodes split chronologically: first 60% for training, next
20% for validation, last 20% for another historical holdout. The bounded
one-parameter ambient relaxation model competes with pack-temperature
persistence. Outputs include episode counts, data gaps, missing heater
state, fitted coefficient and validation/holdout MAE in degrees Celsius.
If there are too few complete sessions the command does not invent gains.

Only numeric allowlisted fields and internal ordering timestamps are read,
not VIN, raw JSON, GPS or car ID. No output includes raw observations.
The command cannot control the vehicle, contact a network, alter Classic
GHOST, store research artifacts or auto-promote models. Episodes are
inferred, not verified actual parking sessions. A historical result is
not post-freeze, genuinely new observation validation.


## M2 thermal model tournament (after real episode-scan failure)

The first complete-episode thermal forecast inspected 88,219 records,
found 2,111 candidate parked episodes and identified 310 usable complete
episodes. In three chronological sets of 186/62/62 episodes
(778/198/233 one-hour anchor pairs), the original one-parameter cooling
model (fraction 0.13002) performed **worse than persistence** on both
later evaluation periods: 1.0058 vs 0.7503 C MAE (34.07% worse), and
0.7688 vs 0.5577 C MAE (37.84% worse). This challenger was correctly
rejected. Missing heater/preconditioning telemetry affected 18,645
parked observations.

The new thermal-tournament command runs five predetermined model families:
persistence, ambient relaxation, one-hour drift, affine thermal, and
asymmetric cooling/warming response. Training uses the first 60% of
complete episodes. The following 20% is used exclusively for model
selection, favoring simpler near-best candidates. The final 20% is
scored once AFTER selection, with episode-balanced MAE. A historical
winner requires at least 10% improvement in validation AND historical
holdout, over half the holdout episodes improved, plus a positive
fixed-seed episode bootstrap 80% lower interval for the MAE benefit.
Otherwise the existing persistence baseline is retained. Even an
accepted research challenger remains in shadow; no automatic promotion.

Heater-state observability is tracked at the eligible episode level.
If a model passes historical accuracy checks but any eligible session
has unknown heater/preconditioning state, the result explicitly warns
that heater evidence was unverified. It never becomes production-ready.

Local command in an isolated checkout:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 thermal-tournament --max-scan 100000

No new Tessie polling, SQLite writes, network access, vehicle controls,
production model integration or autonomous timer. These same historical
records have already been analyzed; the nominal final holdout is NOT
genuinely new prospective validation, nor evidence of causality.


## M3: manual post-freeze thermal shadow experiment

Live Pi tournament: AFFINE_THERMAL gained 15.19% on its selection
validation, then only 3.63% on the 62-episode later historical holdout
(0.5329 C versus 0.5529 C episode-balanced MAE). Only 17 of 310
eligible historical episodes had complete heater/preconditioning state.
The historical challenger **FAILED** its prequalification criteria.
GHOST Classic, its existing production models, and the persistence
baseline must remain unchanged.

GENESIS now supports a **manual**, explicitly authorized diagnostic
freeze of this still-rejected AFFINE_THERMAL candidate. This records a
frozen copy of the model's coefficients, version and SHA-256 fingerprint
in a separate locally private SQLite state database. It uses only
historical episodes available before a freeze watermark (the greater
of the system UTC clock and current source telemetry high-water mark).
Existing frozen experiments are never overwritten or retrained.

From an isolated temporary checkout, use an explicit private ledger:

    mkdir -p /home/ghost/genesis-lab
    chmod 700 /home/ghost/genesis-lab
    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --shadow-db /home/ghost/genesis-lab/prospective_shadow.sqlite3 shadow-freeze --max-scan 100000

Later, manually check whether any **new completed** observed parking
episodes have arrived:

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --shadow-db /home/ghost/genesis-lab/prospective_shadow.sqlite3 shadow-check --max-scan 100000

    python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --shadow-db /home/ghost/genesis-lab/prospective_shadow.sqlite3 shadow-status

Only timestamped source records strictly later than the frozen high-water
mark are included. Any parked session already in progress at the cutoff
is excluded until a new, observable boundary; a session is scored only
after a later observation confirms an activity transition. Current open
tails and gapped/interrupted sessions are not scored. At least 10
completed sessions and 20 one-hour input/outcome pairs must arrive
before a result is calculated. Research results are aggregate,
episode-balanced candidate/persistence errors only; no raw observations,
VIN, GPS, route, ID or precise trip timestamp is stored or displayed.
The ledger records only a new aggregate summary when more completed
sessions are found.

**Critical limits:** The original candidate failed its historical
qualification; even a positive new-data signal cannot automatically
promote it. Many heater signals are missing, and results are labeled
as unverified when that is true. This is a *post-freeze timestamp*
evaluation, not guaranteed arrival-time-verified prospective testing:
late backfills or incorrect source timestamps could defeat its
independence guarantee because the source has no verified ingestion
timestamp. It also has no direct comparison with incumbent GHOST
production predictions. No scheduled jobs, live-Tesla commands,
remote/collective learning, new polling, or production changes occur.

The first score is expected to return AWAITING_COMPLETE_POST_FREEZE_EPISODES,
because only later complete observed parked sessions are eligible.
The production web dashboard and services are not modified. A later
release can add a separately approved recurring read-only scoring
timer once this one-shot experiment is audited.
