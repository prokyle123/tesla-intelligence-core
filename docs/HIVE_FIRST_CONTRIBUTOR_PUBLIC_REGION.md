# Hive Fleet Intelligence: first-contributor public regions (next rollout)

**Development status:** All source and regression tests are on `feature/genesis-v2-foundation`; not yet deployed to the owner's running coordinator, staged Hive client or Classic GHOST control page.

## What is already true on Ghost

- Classic Hive coordinator previously confirmed **one** opted-in reporting installation.
- Owner-authentication patch passed its nonmutating signed-action probe.
- The next private HTTPS setup failed on an **immediate** `curl` attempt to PIN gateway port 8777, before Serve configuration; the health-check script now waits up to 24 seconds and emits a bounded service diagnostic.
- User screenshot shows Western North America selected in the browser, but earlier live API still reported `region_code: null`. A checkbox/dropdown alone is not a saved regional consent.

## New public region choice from the first installation

The previous regional permission was consented under a ten-reporter publication rule. Existing permissions stay nonpublic by default. The new **explicit public-singleton region** setting is independent of Hive monthly error-report consent and the previous broad region sharing permission.

1. The owner first selects and SAVES one of seven world macro-region categories, using PIN-authenticated HTTPS.
2. The owner separately checks an explicit notice that the selected generic world region will be visible publicly even with only ONE reporting installation, then selects **Publish my broad region**.
3. The Hive client sends a token-authenticated `PUT /v1/region-publication` with the new explicit schema. The coordinator migrates existing `region_consents` by adding `public_listing INTEGER DEFAULT 0`, preserving old choices as nonpublic, and stores that new permission only after explicit reconsent.
4. The public exporter includes a single consenting reporter's generic region marker with `visibility: "EXPLICIT_PUBLIC_OPT_IN"` and a count of only public-listed members. Other sub-threshold reporters in that region remain excluded from the public region count.
5. The **Hide my public region** action uses `DELETE /v1/region-publication`. Changing the broad region resets public visibility. Deleting the broad region or revoking the enrollment clears the public listing. Existing ten-member cohorts remain supported.
6. The static/public `network.json` guard validates the new visibility scope and region whitelist; no arbitrary geographic coordinates, names, route traces or extra fields are allowed.

**No route/trip history, precise location or inferred country is submitted.** Monthly model accuracy/errors still follow the existing ten-installation rule because that older consent has not been expanded. Verified unique vehicles/people cannot be inferred from simple enrolled credential counts.

## Deployment gates

Do NOT deploy only the modified private dashboard. The new button requires all four matching layers: (a) a coordinator with the new database migration and routes, (b) updated client `genesis/hive_region_client.py`, (c) reviewed `ghost_tesla_ai/hive_local.py` and owner UI, (d) public export/validator and an approved publication schedule.

Before an upgrade, use the repository's `scripts/hive_ecosystem_readonly_audit.sh` to determine whether coordinator 8778 is started by systemd or an operator-owned foreground/background process. Preserve the existing database with SQLite's online backup API, never a raw file copy under active WAL writes. Stop/restart ONLY the verified coordinator; no fake local data, Classic Home replacement, research model promotion or Hive-consent changes. Refresh the local sanitized public preview and review before publishing it to a remote HTTPS website.

This is a step toward the integrated, installer-supported ecosystem. The current public GitHub Pages feed is not automatically live just because the private local coordinator updates.
