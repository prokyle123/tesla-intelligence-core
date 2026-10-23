# Hive owner controls and per-install enrollment

## Current development implementation

Every installed GHOST node uses two entirely separate secrets:

1. `dashboard-admin.token` is a fresh random key generated locally with
   `scripts/ghost_hive_operator_init.py`. It authorizes only the Hive consent
   actions on **that GHOST instance**. It must remain in a private 0700
   directory as a 0600 file. It is entered in the local Hive dialog and held
   only in the open page's password input; never localStorage, cookies,
   GitHub, analytics, or a public screenshot. Dashboard access by itself
   cannot grant consent or upload a report.
2. `enrollment.token` is a distinct coordinator-issued random credential,
   stored in the same private directory. It authenticates only this
   installation's aggregated monthly submissions to the private Hive.
   The coordinator internally uses its own participant identifier.
   The public dashboard never exposes the enrollment token or individual ID.

Do not automatically opt in, transmit, or enroll merely because software
is installed. Installer-run setup should generate the owner key and
initialize an OFF state. Secure remote coordinator enrollment requires
an explicitly authenticated provisioning workflow rather than sharing one
hard-coded master token across all installs.

## Current private Pi preview

From reviewed source checkout (as the same Linux user that runs GHOST web):

    python3 scripts/ghost_hive_operator_init.py --state-dir "$HOME/genesis-product/state/hive-client"

Existing coordinator enrollment is created independently, as described
in `docs/HIVE_ANALYTICS.md`. Configure `genesis.hive_member` with that
credential in OFF mode. Never post either credential to an issue, chat or
public dashboard.

The GHOST Hive dialog, at `/hive`, now provides:

- owner-key entry, used only in an X-Ghost-Hive-Owner request header;
- preview of six allowlisted monthly fields in human-readable units;
- explicit affirmative consent to pseudonymous aggregate sharing;
- separately confirmed one-time upload of the exact displayed report;
- immediate opt-out; manual remote revocation and deletion confirmation.

The server rejects missing keys, missing or cross-origin headers,
non-JSON requests, missing acknowledgments, unreviewed uploads and
changed data since preview. Read-only local analytics remain unchanged.
Data submission is **manual**, never automatic at this phase.

## Future one-command production installer

After installer integration testing on a fresh system:

- Install one GHOST package; Hive appears as one additional page.
- Generate a different local owner key on each new install, with no
  network transfer and consent OFF by default.
- Show a secure enrollment/setup wizard that authenticates against the
  published HTTPS Hive service and receives a unique, revocable credential.
- Store state and credentials outside the application code directory in
  service-user-owned protected storage; make backup/restore aware of
  rotating identifiers and never clone secrets onto a second vehicle.
- Review fields, ask consent, upload only monthly aggregated outcomes
  with an explicit user-approved transfer schedule, retry/idempotency,
  receipts, and the ability to revoke. Default OFF on upgrade as well.
- A public read-only Hive site consumes only sanitized snapshots, never
  raw server tables, user credentials or GHOST private APIs.

**Privacy limits:** The coordinator can associate a monthly report with
an enrolled installation. This is pseudonymous sharing, **not anonymity,
secure aggregation or federated neural-network training**. Model weights
remain unshared until a separate privacy, integrity and compatibility review.

## Safe deployment on a customized existing GHOST

`scripts/ghost_hive_update.py` upgrades only
`ghost_tesla_ai/hive_local.py` and `web/templates/hive.html` with exact
base-hash guards and an independent backup directory. It does not edit
`index.html`, `server.py`, the collector or the training services.
Run `--check` first, then `--apply`, then restart **only** the web service.
On a failed verification, use the checked `--rollback` option and restart
the web service again. Existing research state and OFF consent survive.
