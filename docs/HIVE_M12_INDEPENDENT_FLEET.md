# GHOST HIVE M12 — Independent Fleet Intelligence

**Branch:** `feature/genesis-v2-foundation` · development/review only until installed on Ghost.

## Purpose

Show the real, private comparison between **this enrolled GHOST installation** and
other reporting installations, without comparing the installation to an average
that includes itself. **No additional telemetry field, VIN, GPS, trips or
model weights is transmitted.** This milestone works with the existing
strict six-field monthly temperature error report.

### Architecture

1. `genesis/hive_peer_comparison.py` computes a leave-one-out, **same UTC month**
   comparison from the coordinator's already accepted `monthly_research`
   rows. Each individual requester is excluded in SQL.
2. `GET /v1/member-comparison` on the loopback Hive coordinator requires
   the installation's existing bearer enrollment token. It returns bounded
   monthly MAE/scores, qualified peer counts and status **without identities,
   single-peer unconsented results, account numbers or tokens**.
3. A second privacy gate determines the peer cohort:
   - With fewer than **ten OTHER reporting installations** in a given month,
     include only peers who independently granted the separate `public_monthly`
     consent for that month.
   - With ten or more OTHER installations that month, the original
     consented large-cohort release rule permits the aggregated peer data.
   - Other installations' unconsented small-group values are excluded, not
     added to a partially public group.
   - The peer count is suppressed when no eligible peer data exists, even if
     the coordinator holds private rows.
4. `genesis/hive_peer_client.py` fetches only from the endpoint already
   configured for this installation and uses its existing private token file.
   It does **not** write consent or submit a new research report.
5. The private Classic GHOST page fetches the result using
   `POST /api/hive/control/peer-compare`, signed by the already-PIN-authenticated
   HTTPS gateway. The page receives **no bearer token**.
   - **Never add an unauthenticated GET route for this personal peer result.**
     Raw port 8766 remains read-only for non-sensitive local fleet summaries,
     but does **not** grant personalized peer benchmarking.
   - Signed actions bind the request body, exact path, Origin, timestamp and
     single-use nonce. Spoofed headers/replays fail.
6. The Fleet Intelligence dashboard adds an honest separate panel with monthly
   own MAE, peer MAE, peer score count, peer installation count, and descriptive
   difference, or a meaningful no-peer state.

### What M12 does NOT claim

- A single installed participant cannot be its own independent fleet benchmark.
- One report is neither a verified independent person nor a verified distinct
  Tesla. The coordinator counts enrolled reporting installations only.
- A self-reported monthly **MAE in °F** is not within-2°F accuracy. Existing
  Hive monthly payload cannot compute a fleet-wide within-2°F percentage.
- Without trip conditions, vehicle, battery, weather regime and calibration
  matching, a lower MAE does not prove a superior model.
- There is no neural/federated model training, automatic promotion, VIN, GPS,
  trip history upload, remote vehicle control or covert consent change.
- There is **no 100-score display gate**. A local resolved score is displayed
  locally as observed; the existing monthly transport schema requires 25 scored
  outcomes *per upload* as its original validation rule, **not 25 cars**.
- Legacy reports remain protected by original cohort publication constraints;
  no invisible reduction of past privacy promises.

### Tested behavior

- One enrolled installation → self monthly score visible privately, no peer score.
- Two installations with only one nonpublic peer → peer values withheld.
- Two installations whose peer explicitly granted public-monthly permission →
  comparison available for the same month, requester excluded.
- Ten OTHER legacy-consented reporters → qualified aggregated peer cohort.
- Previously unconsented months → not retroactively published.
- Enrollment deletion → its monthly records are removed from the comparison.
- Unauthorized/no bearer coordinator reads, unsigned raw GHOST control calls
  and replayed gateway proofs are rejected.

### Guarded on-Pi deployment

```bash
bash scripts/hive_m12_deploy.sh check
bash scripts/hive_m12_deploy.sh install
```

Only run after pinning and verifying the exact GitHub development revision.
The deployment verifies the already managed systemd coordinator, makes a private
SQLite online backup, stages **only tracked Git code**, and switches the
coordinator service with rollback to the previous unit on failure. It then
updates the isolated GENESIS preview and approved Hive-owned Classic files;
neither the collector nor production model services are restarted. The frozen
M9/M10 research files are SHA-verified unchanged.

After rollout, the new independent comparison panel requires sign-in through
the existing PIN-protected HTTPS GHOST address. A direct untrusted HTTP browser
may see the existing public/local aggregates but **not** the owner-only
independent peer evidence.

## Next integrated milestone

End-to-end multi-installation onboarding: managed external HTTPS coordinator,
per-installation token issuance, automatic installer enrollment only after
explicit opt-in, authenticated monthly score refresh, revocation and deletion,
and a sanitized public feed publication pipeline. Add a new separately
consented metric protocol only if more statistical features are needed; don't
pretend the existing six-field payload contains sensor arrays or per-drive data.
