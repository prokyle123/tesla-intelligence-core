# GHOST Hive — simple hourly participation

## Owner experience

The single GHOST Hive page now offers one choice: **Yes, contribute automatically every hour**.
Read the short disclosure once, press Yes, then GHOST automatically checks for new qualified
battery-temperature prediction outcomes hourly. The backend holds the enrollment credential
outside the app's web root; the browser never receives it and no owner token is pasted.
**Turn off contribution** immediately prevents future transfer after any already-running
sync finishes. Revoke/Delete is a separate, irreversible enrollment action.

## Current narrow transfer policy

Current protocol permits only the validated six-field monthly aggregate:
`schema`, `metric`, `month`, `scored_predictions`, `total_abs_error_c`, `source`.
This uses the user's actual resolved GHOST prediction audit. No VIN, GPS, identity,
routes, raw telemetry, exact trip timestamps or model weights. It is **pseudonymous**,
because the private coordinator knows the enrolled installation; NOT cryptographic
anonymity, differential privacy, or actual federated neural-network weight learning.
Additional data families will require a new consent scope and protocol revision.

The hourly timer recomputes the monthly totals and sends only when the approved
report changes. The coordinator upserts by contributor and month, so repeated hourly
checks do not create duplicate members. Missing/insufficient evidence and OFF consent
cause zero network uploads. Transient failures do not update the local success marker.
Opt-out shares a file lock with the worker to prevent uploads continuing after opt-out
has completed.

## Owner identity — no pasted secret

The current GHOST web service does NOT have a first-party authenticated owner
account. Exposing a shared administrator key inside a webpage would allow anyone
with web access to enable transfer without the owner's consent.

For the **Pi development preview only**, mutating Hive actions are accepted
from a browser opened through an *authenticated SSH localhost tunnel*,
with same-origin checks and blocked forwarded headers. From Windows PowerShell:

    ssh -N -L 127.0.0.1:8766:127.0.0.1:8766 ghost@YOUR_PI_TAILSCALE_ADDRESS

Keep the tunnel window open and visit `http://127.0.0.1:8766/hive`.
Existing regular dashboard/Tailscale access is unchanged and remains read-only
for consent actions. This is not a production replacement for authenticated
owner accounts; remote multi-user deployment must use an authenticated gateway.

## Deploying the independent hourly backend safely

Stage the reviewed feature branch through `scripts/genesis_stage_preview.sh`.
After the client state is configured with its private `enrollment.token` (OFF)
and you have verified the files, install an independent hourly one-shot timer:

    sudo bash scripts/hive_hourly_timer.sh install

View status or disable the timer:

    sudo bash scripts/hive_hourly_timer.sh status
    sudo bash scripts/hive_hourly_timer.sh disable

The systemd oneshot runs as the existing GHOST service user; `ProtectSystem=strict`
permits writing only its private Hive state directory. It does not restart
Classic GHOST, fetch Tesla telemetry, enable consent, or initiate an immediate upload.

The browser enables local hourly consent only after this timer is active.
Actual first upload occurs on the next scheduled timer invocation after consent
and only with sufficient qualified evidence. For an existing customized Ghost,
update the two Hive-owned files using guarded `scripts/ghost_hive_update.py`
with a NEW private backup directory; never replace the entire Home server/template.

## Final multi-instance installer plan

Each new installation should generate a random local owner identity and enroll
with a unique coordinator-issued revocable credential over authenticated TLS.
Neither shared static IDs nor enrollment secrets belong in public GitHub.
After first-install authentication, make Hive optional and OFF by default;
offer one YES for the approved protocol and an hourly timer, plus one OFF
and a separate erase/revoke action. Consent/schedules survive upgrades but
are never silently enabled on install. Do not distribute or clone a Pi
installation's keys to another vehicle.

Production requirements still include a real web owner-login/authenticated
reverse proxy, safe remote bootstrap enrollment, TLS pinning/verification,
privacy audit, reliable backoff/monitoring, deletion/backup retention, and
public group suppression for small cohorts.