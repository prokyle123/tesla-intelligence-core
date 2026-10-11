# October 2026 — GHOST development update

**Tesla Intelligence Core · Live Raspberry Pi source snapshot · October 11, 2026**

> [!IMPORTANT]
> **Development snapshot, not a new tagged release.** This page documents code exported from the running GHOST Raspberry Pi on October 11, 2026. It does not imply that optional systemd timers are enabled on every installation. All forecasts remain advisory; the software does not send vehicle control commands.

[← Project overview](../README.md) · [Changelog](../CHANGELOG.md) · [Architecture](ARCHITECTURE.md) · [Dashboard screenshots](images/dashboard-overview.png)

---

## At a glance

| Area | Improvement | Benefit |
| --- | --- | --- |
| **Winter Readiness** | Switchable RIGHT NOW / NEXT DEPARTURE gauge with two independently recorded score histories | Makes current conditions distinct from future departure predictions |
| **Departure intelligence** | Multi-trip pattern learning and automatic candidate rollover | Moves to another supported prediction when an expected departure expires |
| **Trip accountability** | Six isolated shadow learners | Tests route, timing and SOC predictions without modifying production |
| **Energy planning** | Conditional 24-hour multi-leg SOC-demand preview | Surfaces possible energy needs without inventing a known destination |
| **Models** | Neural challenger training, truth comparisons and governor gates | Prevents new generations from automatically replacing better predictors |
| **Charging protection** | Supercharger/DC fast-charge exclusions for Level 1-rate learning | Protects overnight SOC projections from high-power sessions |
| **Publishing** | Current Pi source synchronized with privacy exclusions | Makes October improvements available for code review |

## 1. Winter Readiness: one dial, two meaningful modes

The dashboard keeps its single primary gauge. A selector changes the **score, status, readiness explanations and 12-hour chart** together.

| | **RIGHT NOW** | **NEXT DEPARTURE** |
| --- | --- | --- |
| Question | “What condition is the car in if I leave now?” | “What condition is expected when I next leave?” |
| Main inputs | Measured SOC and pack temperature; current operating conditions | Predicted departure/arrival SOC; thermal outlook and learned behavior |
| Trip reserve | **Conditional reference-commute** estimate; not a verified route | Existing learned departure and representative-trip estimates |
| Graph | Independently recorded NOW score history | Existing projected-score history |
| Default | **Yes** | Switchable |

**Changes and improvements**

- New **RIGHT NOW / NEXT DEPARTURE** selector without introducing a second full-size dial.
- NOW uses a **separate weighted calculation**, rather than relabeling the projected score.
- Mode-specific limiter details and score-accounting displays.
- Two real **12-hour score histories**. NOW's history starts when installed; it is **not backfilled with fabricated past values**.
- Future readiness remains an **estimate**. Unknown future weather, charging or manually initiated preconditioning can change actual outcomes.

**Code:** [winter_board.py](../ghost_tesla_ai/winter_board.py) · [winter_dual_mode_v1.py](../ghost_tesla_ai/winter_dual_mode_v1.py) · [winter_score_history.py](../ghost_tesla_ai/winter_score_history.py) · [winter_score_sampler_v1.py](../ghost_tesla_ai/winter_score_sampler_v1.py) · [dashboard template](../web/templates/index.html)

> [!NOTE]
> Background sampling is implemented in source, but this GitHub sync does **not** verify that the sampler timer is enabled on a particular installation. Score-history graphs measure how a score changes over time, **not** its prediction accuracy.

## 2. Departure learning and rollover

GHOST learns recurring **weekday, weekend and multiple-trip departure patterns** from observed drive starts, subject to confidence and evidence thresholds.

1. **Multiple candidate times.** A day can have more than one recurring departure.
2. **Automatic rollover.** As a predicted time passes out of its upcoming window, the learner can select the next supported departure. An evening prediction was observed rolling over to a next-morning candidate when the car remained parked.
3. **Evidence-based behavior.** Missing a predicted trip does not automatically create a made-up replacement time.
4. **Separate measures.** Schedule confidence does not imply route certainty or a guaranteed arrival-SOC forecast.

**Code:** [departure_learning.py](../ghost_tesla_ai/departure_learning.py) · [readiness.py](../ghost_tesla_ai/readiness.py)

## 3. Six shadow trip-intelligence layers

These modules were present in the October 11 export. **None automatically promotes findings into production readiness, departure prediction or neural inference.**

| Layer | Function | Key safety rule |
| --- | --- | --- |
| **v1 — Sequence** | [Trip sequence and recurring chains](../ghost_tesla_ai/trip_sequence_shadow.py) | Rejects unsuitable fragments and stale location evidence |
| **v2 — Stable sites** | [Anonymous parking locations and observed links](../ghost_tesla_ai/trip_location_context.py) | Nearby places are **not** automatically treated as identical |
| **v3.2 — Route accountability** | [Frozen pre-trip predictions and scored full drives](../ghost_tesla_ai/trip_outcome_v3.py) | Moving-vehicle captures are invalidated |
| **v4 — Verified feedback** | [Departure/SOC bias evidence and advisory corrections](../ghost_tesla_ai/trip_feedback_v4.py) | Requires more verified trips; changes are **not** applied automatically |
| **v5 — Time-only coverage** | [Forecasting departure times without GPS certainty](../ghost_tesla_ai/trip_coverage_v5.py) | Does not invent destinations or SOC outcomes |
| **v6 — Unified comparison** | [Route/time-only evidence and relationship checks](../ghost_tesla_ai/trip_relationship_v6.py) | Avoids double-counting overlapping predictions |

**What this enables**

- Scoring predictions **captured before** a trip, instead of evaluating a retrospectively fitted guess.
- Separating **known routes** from **time-only** departure patterns.
- Measuring timing, destination and battery errors without silently correcting the production engine.
- Tracking observed multi-stop chains while preserving uncertainty.

**Evidence limitation:** The October 9 read-only audit had **one** scored GPS-route forecast and **two** separate time-only forecasts. Those are early diagnostic examples, **not statistically reliable long-term accuracy measurements**. A time-only match can correspond to a later departure rather than the original work departure.

**Additional advisory module:** [trip_energy_preview_v1.py](../ghost_tesla_ai/trip_energy_preview_v1.py) estimates possible SOC demand across up to 24 hours of supported legs. It does not assert an unverified destination or alter the official Winter Readiness score.

## 4. Neural network and model accountability

The predictive stack continues to distinguish **training**, **evaluation** and **serving**:

- Conventional machine-learning baselines remain available.
- The PyTorch GRU operates as a **challenger**, with comparisons against held-out historical observations.
- The neural governor uses validation/qualification gates; a new generation is **not** an automatic production promotion.
- Prediction auditing remains separate from the operational Winter Readiness score.
- More collected telemetry becomes eligible for future training cycles; it does **not** imply that already-trained model artifacts have learned newer drives.

**Code:** [neural_v4.py](../ghost_tesla_ai/neural_v4.py) · [neural_governor.py](../ghost_tesla_ai/neural_governor.py) · [neural_audit.py](../ghost_tesla_ai/neural_audit.py) · [predict.py](../ghost_tesla_ai/predict.py)

> [!TIP]
> Judge model improvements using **held-out error and subsequently verified real-world outcomes**. Model generation counts and visual confidence indicators are not substitutes for demonstrated accuracy.

## 5. Charging safety: DC fast charging is not Level 1

### The issue

The October 9 audit found a high-power charging session with approximately **34.5 kWh added in 20 minutes** and **230 kW peak charger power**. Its reconstructed event nevertheless showed **0 kW average power**, allowing the old low-power filter to consider it for Level 1 learning.

### The correction

- **Power-field selection:** A zero AC-input reading no longer hides positive charger-power evidence when reconstructing an event.
- **Independent plausibility checks:** Level 1 candidates are evaluated using recorded power, energy gained per unit time and SOC-gain rate.
- **History preserved:** DC sessions remain in the event/telemetry record but are excluded from inappropriate slow-charge learning.
- **Narrow scope:** The source fix did not wipe databases, retrain models, reset neural generations or change trip-learning timers.

| October 9 verification (60-day window) | Previous filter | Protected filter |
| --- | ---: | ---: |
| Charge events examined | 627 | 627 |
| Accepted Level 1 samples | 55 | 53 |
| Learned median SOC gain | 1.385 pp/hour | **1.374 pp/hour** |

The median shifted only slightly because a median already resists extreme values. **Preventing repeated fast-charge contamination is the main improvement.** These are historical measurements, not a promise of identical rates on other vehicles.

**Code:** [event_engine.py](../ghost_tesla_ai/event_engine.py)

## 6. Publishing, privacy and deployment scope

The October source sync published the Pi's current Python source and dashboard, then updated project documentation.

| Included | Deliberately excluded |
| --- | --- |
| Current Python application modules and dashboard template | SQLite telemetry and charging logs |
| Six shadow learners and advisory preview code | Private route/site registries and GPS coordinates |
| Readiness and charging classification improvements | Tessie/EcoFlow credentials, PINs and environment files |
| Existing public repository resources | Trained model artifacts and private state databases |
| Updated development documentation | Live service units, machine-specific timer configuration |

The on-Pi collector syntax-checked **44 Python files** before export. That is a source check, **not proof of a clean fresh install** using the public repository alone. The live systemd unit definitions and timer enablement state were not copied.

### Screenshot status

Existing [repository screenshots](images/dashboard-overview.png) remain available, but some predate the new selector. No concept mockup was uploaded as a real production screenshot. A refreshed image can be added after capturing the installed UI and reviewing it for private information.

---

## Further reading

[Project README](../README.md) · [Changelog](../CHANGELOG.md) · [Architecture](ARCHITECTURE.md) · [Feature matrix](FEATURE_MATRIX.md) · [Installation guide](INSTALL.md)

*Last updated October 11, 2026 · Source reference: [741ff0d](https://github.com/prokyle123/tesla-intelligence-core/commit/741ff0da322ad30452f20e756a548293ce380e04).*
