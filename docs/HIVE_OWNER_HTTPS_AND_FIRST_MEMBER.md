# GHOST Hive owner access and first-contributor onboarding

## Owner access: no SSH tunnel required after secure first-run setup

The private GHOST Hive page **reads** aggregate health data on port 8766. Enrollment, contributor removal, consent and region changes are write operations and require **authenticated owner access**. The previous developer-preview shortcut accepted only an SSH-forwarded loopback browser, so a Tailscale/LAN dashboard could render normally while its buttons returned `OWNER_AUTHORIZATION_REQUIRED`.

### PIN gateway and private HTTPS Serve

GHOST already supports a PIN-protected dashboard gateway on Pi loopback port 8777 (the optional existing Tailscale Funnel service). The Hive control endpoint now accepts a **short-lived HMAC-signed, single-use proof** issued by that gateway **only after a valid PIN session**, not an unauthenticated `X-GHOST-Funnel-Authenticated` header. Each proof binds request method, exact Hive control path, HTTPS browser Origin, JSON request body digest, timestamp and random nonce. The authenticated browser gets no Hive admin token or access to PIN secrets.

- The gateway checks HTTPS browser origin matches the target HTTPS host (including trusted, local reverse-proxy host forwarding). Plain HTTP requests never receive remote action proofs.
- Backend accepts gateway proofs **only over loopback**, and rejects forged signatures, wrong requests, expired/replayed nonces, unsafe PIN files and missing trusted session secrets.
- PIN session cookie remains `Secure`, `HttpOnly` and `SameSite=Lax`. PIN login is rate-limited by the existing gateway implementation.
- The old authenticated SSH-forwarded loopback path remains operational for development and recovery.
- Direct LAN or tailnet **HTTP** to `http://PI:8766` remains read-only for these owner actions. This is intentional, not a broken consent button.

A first installer can optionally select **private HTTPS dashboard access through Tailscale Serve**. Setup verifies an already-connected tailnet, prompts for a one-time PIN if missing, enables the local gateway, and configures private HTTPS **only if no existing Serve/Funnel configuration is found**. It does **not** automatically publish public Internet Funnel access.

For existing Ghost owners after a reviewed scoped code update:

```bash
bash scripts/hive_owner_gateway_deploy.sh check
bash scripts/hive_owner_gateway_deploy.sh install

# Optional if no existing PIN HTTPS Serve/Funnel:
bash scripts/hive_owner_private_https_setup.sh
```

When an existing PIN-protected Funnel/Serve domain is in use, the setup script preserves it. Ensure the existing domain forwards to the PIN gateway on `127.0.0.1:8777` rather than directly exposing raw GHOST port 8766. To remove or change sharing, browse that HTTPS address, sign in, then open `/hive`. **No SSH tunnel required in normal operation.**

The **guarded owner updater** replaces only `ghost_tesla_ai/hive_local.py`, `ghost_tesla_ai/funnel_gateway.py`, the new `ghost_tesla_ai/hive_owner_proof.py` and the Hive owner's help text in `web/templates/hive.html`, after matching exact reviewed old source bytes. It backs up old files, restarts only Classic Web and an already-running gateway, and probes a malformed report-preview request to verify authorization *without changing consent, uploading, revoking or deleting anything*. Any unexpected live source edits cause preflight to stop.

## Real first-contributor reporting

The currently enrolled owner's coordinator reports **1 actual opted-in reporting installation**, not a simulated count. The Fleet v1.3 private display shows that overall count even if monthly participant group statistics are withheld. The separate optional region choice currently shows **Not selected** on this installation.

Country ranking, city rankings and actual `where members drive` maps **cannot** be obtained from current six-field battery-temperature monthly aggregates. The owner may voluntarily choose one of seven broad world regions; the private owner view can show that choice instantly. Existing coordinator public regional cohorts use a ten-same-UTC-month-reporting-member minimum, which does not apply to overall enrollment totals. A `0` public qualified region count therefore does not mean `0` reporting installations.

**Do not silently reduce an existing participant's region-release threshold**: the original opt-in text explicitly described the ten-node guard. Releasing a lone installation's opted-in region publicly needs an **additional explicit singleton-publication permission** and fresh consent, with deletion/withdrawal reflected in future public exports. Until that separate feature exists, publish only the honest overall contributor total of 1 and the existing sanitized public feed. Exact GPS traces, homes, workplaces and routes must remain private by default.

## Needed for the complete product

- Make PIN-protected private HTTPS a smooth install-time option and test on mobile/desktop, without public Funnel exposure by default.
- Add owner-visible setup/connection status, PIN reset, session revocation and structured auth audit. Test rate-limiting and signed gateway proof across multiple service restarts.
- Deploy the Hive coordinator behind managed TLS and validated scoped tokens; add independent node enrollment/revocation, backup and abuse protection.
- Add an optional **separately consented** low-cohort public-region disclosure mechanism, only for nodes choosing that visibility. Do not retroactively publish preexisting selections.
- Build optional country-level statistics through a newly scoped user-selected country consent field; never infer routes from telemetry or pretend non-existent country data are already uploaded.
- Publish validated and fresh sanitized `network.json` via approved HTTPS, separate from local previews, and test GitHub Pages freshness.
- Continue GENESIS M9–M11 trials and prospective per-installation model research without changing working Classic models or Hive data permissions.
