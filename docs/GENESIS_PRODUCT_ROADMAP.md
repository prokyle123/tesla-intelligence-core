# GHOST GENESIS — Product roadmap (v0.2 preview)

Status: **developer preview, separate from Classic GHOST**. Never use the
Classic installer to deploy this unreleased branch to a working Pi. Do
not advertise these retrospective associations as real-world discoveries.

## Product intent

The final product is an installed local-first intelligence laboratory
that can investigate Tesla telemetry, measure future predictive skill,
explain its confidence and failures, retain evidence, and propose safe
new experiments; it never drives the car. Hivemind and Fleet Observatory
remain future opt-in services and are **not implemented federated learning**.

## Product milestones

| Gate | Deliverable | Current state | Release criterion |
| --- | --- | --- | --- |
| P0: Research integrity | Numeric-only telemetry read; isolated hypotheses; no vehicle control | Implemented, exploratory | Fail-closed multi-vehicle, no source writes, documented interpretation |
| P1: Product core | One operator-invoked cycle, isolated research ledger, historical experiment status | **Implemented in branch** | Deterministic tests and real Ghost smoke test, reproducible recovery |
| P2: Research console | Separate browser dashboard, history and hypothesis status | **Loopback preview in branch** | Real Pi screenshot QA on PC and mobile, proper authenticated entrypoint |
| P3: Prospective research | Frozen candidate, completed post-freeze parking episodes, drift/history | Manual diagnostic exists | Verified arrival-time/episode boundaries, sufficient new data, incumbent GHOST forecast comparison |
| P4: Release packaging | One-command install/update/rollback, controlled CPU/RAM, Python dependency self-check | Staging/rollback preview only | Fresh Raspberry Pi installation + Debian/WSL smoke; no Classic downgrade |
| P5: Product launch | Complete docs, onboarding, health alerts, backup/restore, monitoring | Not yet | Signed release, security review, performance soak, owner approval |
| P6: Hivemind/Fleet | Opt-in privacy-preserving cohort research | Fictional offline demo only | Independent threat model, privacy/transport review, explicit opt-in; not a v2 launch blocker |

### First product workflow (not installed or running automatically)

From the checked-out feature branch as a normal nonroot Linux user:

~~~bash
bash scripts/genesis_stage_preview.sh stage
cd "$HOME/genesis-product/current"

# If python3 cannot import Flask, select the working Classic venv interpreter
# without installing anything into Classic itself. Example:
# PY=/opt/ghost-tesla-ai/venv/bin/python
PY=python3

"$PY" -m genesis.cli \
  --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 \
  --product-db "$HOME/genesis-product/state/product.sqlite3" \
  product-cycle --max-scan 100000 --save

"$PY" -m genesis.workspace \
  --data-dir "$HOME/genesis-product/state" --port 8767
~~~

Preview server is deliberately restricted to localhost. In a **separate
Windows PowerShell session** on a trusted PC, open an SSH port forward:

~~~powershell
ssh -N -L 8767:127.0.0.1:8767 ghost@YOUR_GHOST_TAILSCALE_IP
~~~

Then navigate locally to http://127.0.0.1:8767/genesis on the PC.
Port 8767 must be unused locally; change the local port in the tunnel
if needed. Keep the tunnel terminal open; Ctrl+C shuts it down. No
remote internet or Tailscale listening socket is opened by GENESIS.

To restore a previous staged code snapshot, run:

~~~bash
bash scripts/genesis_stage_preview.sh rollback
~~~

This only switches a private symlink; it does not restart a process.
Stop a running preview first and restart using the restored code.
Rollback does not change experiment data, Classic GHOST or its models.

## Core design boundaries

- **Production source:** SQLite in read-only mode. May contain Tesla data;
  the product never stores/export identifiers, positions or route history.
- **Working state:** private dedicated home directory; only aggregate
  scientific findings, counts and reasons; no raw telemetry copies.
- **Web UI:** GET/HEAD only. Loopback preview has no login; do not expose
  it directly through public ingress, funnel or LAN. Release requires an
  authenticated gateway.
- **Learning:** the Architect runs preapproved bounded scientific
  questions, not unrestricted generated code. No model is automatically
  promoted or used to command the car.
- **Safety:** no changes to /opt/ghost-tesla-ai, /etc/ghost-tesla-ai,
  /var/lib/ghost-tesla-ai, systemd units, TeslaMate, Tessie polling or
  Classic readiness forecasts from this stage/preview.
- **No timers:** scheduled research must be reviewed and enabled in a
  later milestone, with quotas and proof it cannot interfere with Classic.
- **Prospective caveat:** source timestamps are not verified ingestion
  timestamps and thermal/heater observation can be incomplete. A historical
  or tentative post-freeze gain is not evidence of verified product skill.

## Next engineering tranche

1. Read-only live Pi acceptance of the new operator product cycle + dashboard.
2. Authenticated gateway integration while preserving the Classic boundary.
3. Typed release schema, signed immutable versions, backup/rollback contract.
4. Evidence-grade prospective validation using new actual outcomes and
   calibration against incumbent GHOST predictions.
5. Controlled opt-in local scheduler with performance caps, retries and audits.

No claim of a final general-availability release is made at this stage.
