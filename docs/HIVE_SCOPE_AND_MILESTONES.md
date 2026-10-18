# GHOST GENESIS + HIVE — feature-scope ledger

This is the original combined intent: local, evidence-led Tesla AI research
plus an optional privacy-conscious research network. **Implemented** means
a reviewed development feature exists; it does NOT imply safe deployment to
the Internet or functional cross-vehicle federated learning.

## Current state (October 2026)

| Track | Implemented in development | Still required |
|---|---|---|
| Existing GHOST Home | Production readiness, trip learning and trained models continue independently | No changes to Home or autonomous model promotion from Genesis |
| GENESIS local research | Numeric-only, read-only hypotheses, episode-aware thermal experiments, isolated ledger and prospective diagnostic shadow | Truly prospective evidence, drift checks, safe per-Pi resource budgets and authenticated release |
| Local Hive | Independent loopback coordinator, explicit opt-in, monthly aggregate submission, hourly timer and deletion/revocation | External-node onboarding, TLS, isolated hardened coordinator hosting, backups, rotation and abuse/rate-limit review |
| Private Hive dashboard | Live scored local outcomes, lifetime/monthly accuracy, 7d/30d rolling temperature accuracy and MAE, voluntary region controls | More meaningful error breakdowns by forecast horizon, battery state and ambient temperature (local-only unless separately consented) |
| Public Hive dashboard | Real total reporting installations, cohort release tracking, cohort MAE only at ≥10 same-month reporting installations, approved broad opt-in regions only at ≥10 same-month regional installations | Reviewed public HTTPS sanitized snapshot feed and confirmed GitHub Pages deployment |
| Collaborative intelligence | Auditable summary collection and a synthetic research simulator | Cross-installation model evaluation, signed compatible artifact format, leakage tests, true federated training or secure aggregation, explicit additional opt-in |

## What the current public dashboard cannot honestly show

- **±2°F fleet accuracy:** existing consented six-field monthly report provides
  forecast count plus total absolute error, but **not** the number of forecasts
  that hit the ±2°F target. MAE cannot be converted to hit rate. A future
  explicitly consented protocol version would need a bounded monthly hit count,
  backwards-compatible rollout and replay/validity tests.
- **7-day/30-day member counts:** current transport sends a monthly aggregate.
  The public site does not collect day-level member histories, and must not
  invent them or reverse-infer individual reporting schedules.
- **Independent fleet baseline / model improvement:** needs a documented
  reference evaluation with genuinely out-of-sample outcomes; no model-training
  accuracy can be substituted.
- **Contributor map:** selected broad regions only, with real thresholds.
  The decorative globe is **not** a live vehicle-location map.
- **Federated training:** the server currently receives per-installation
  pseudonymous monthly aggregates; no secure aggregation, differential privacy
  or real exchange of learned model weights is running.

## Next development gates

1. **Local evidence depth:** show honest 7/30-day quality and sample counts,
   then add local-only diagnostic breakdowns by forecast family and horizon.
2. **Public data delivery:** publish only validated `network.json` over an
   operator-reviewed HTTPS static endpoint; keep the coordinator on loopback
   until its independent hardening and hosting review is complete.
3. **Research metric v2:** design a new aggregate hit-count protocol with
   an updated on-device plain-language consent review. Preserve old clients
   and never expand existing opt-ins silently.
4. **Reliable multi-install onboarding:** automatic, device-specific secret
   issuance; revocation; rate limiting; secure hosting and documented deployment.
5. **True multi-vehicle science:** prospective and baseline-calibrated quality
   comparisons; later consider signed model artifacts, secure aggregation,
   and opt-in federated training after threat-model/security validation.
6. **Release quality:** tests, Raspberry Pi load soak, verified rollback,
   source/content audits, documented limitations and a signed release.

## Boundaries that do not change

- Do not write GHOST production SQLite from Hive/Genesis research.
- Do not control the car, poll or wake it additionally, or promote models.
- Do not upload VIN, GPS, routes, exact timestamps, raw sensor rows or model
  weights through the current monthly consent.
- Do not publish small-cohort accuracy, raw error traces or per-node rows.
- Do not present reporting installations as verified unique humans.
- Preserve the existing Home dashboard and release all experiments separately.
