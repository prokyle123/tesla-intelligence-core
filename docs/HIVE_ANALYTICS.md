# Hive Analytics — GENESIS development preview

This separate responsive contributor analytics dashboard is designed in the dark, clean
DriveLab/GHOST visual style: summary statistics, monthly activity, research quality
graphs, and a six-month breakdown, with readable terminology.

## Group metrics and privacy

- Contributing nodes: distinct enrolled, enabled installations in an eligible month.
  This is NOT a verified count of unique people.
- Predictions checked: total research evaluation episodes in eligible monthly cohorts.
- Average prediction miss: episode-weighted mean absolute error in degrees Fahrenheit
  (multiply the Celsius error by 1.8, do not add 32).
- Returning nodes: participating in this and last month, displayed only if BOTH months
  independently have at least 25 eligible enrolled nodes.
- Under-threshold months are entirely withheld rather than disclosed as tiny counts.
- The server stores each enrolled node's private aggregate separately. This is NOT
  secure aggregation, differential privacy, or anonymity, and small-cohort
  suppression alone is not an anonymity guarantee.

## Local-only setup

On a Pi where GENESIS product preview is staged under /home/ghost/genesis-product/current:

    bash ~/genesis-product-source/scripts/hive_preview.sh start

Check or stop it:

    bash ~/genesis-product-source/scripts/hive_preview.sh status
    bash ~/genesis-product-source/scripts/hive_preview.sh stop

The independent server listens only on 127.0.0.1:8778, keeps its private
database in ~/genesis-product/state/hive-server/ and does not touch Classic GHOST.

In a separate Windows PowerShell window:

    ssh -N -L 127.0.0.1:8778:127.0.0.1:8778 ghost@YOUR_GHOST_TAILSCALE_IP

Then visit http://127.0.0.1:8778/hive in your browser. The "View sample data"
toggle loads six months of explicitly FICTIONAL group statistics. No telemetry
is sent or saved by the sample view.

## Transfer protocol status

The existing separate Hive client is OFF by default. It allows only synthetic
test submissions following TWO explicit choices: configure with
--enable-synthetic and send-test --send. A dry run sends nothing.
Authenticated coordinator enrollment and revocation are supported.
No real vehicle sensor observations or real aggregate telemetry can be
uploaded with this client version. No automated timer is installed.

A live public Hive deployment still needs a separately authenticated TLS
gateway, consent and revocation UX, verified real post-freeze aggregates,
a privacy review, secure transport and retention, monitoring, abuse limits,
and independent deployment/rollback tests. Never publish the loopback preview
to an untrusted network.

## Release gates

Implemented: private coordinator; strict aggregate-only schema; manual
synthetic opt-in; monthly cohort threshold; responsive dashboard; synthetic
sample mode; privacy checks. Outstanding: phone/desktop visual QA on Ghost,
proper multi-user security, genuine research provenance, real consent lifecycle,
hosted operations, and production release review.
