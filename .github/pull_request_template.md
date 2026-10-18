## What changed?

Describe the change and why it is useful.

## Runtime safety

- [ ] Existing `/etc/ghost-tesla-ai` config is preserved, or migration is documented.
- [ ] Existing `/var/lib/ghost-tesla-ai` history/models are preserved, or migration is documented.
- [ ] No credentials / VINs / private telemetry were added.
- [ ] `python3 -m compileall -q ghost_tesla_ai` passes.

## Testing

Describe how you tested the change.

## Screenshots

If this changes the dashboard, include before/after screenshots with private vehicle information redacted.

## Public release hygiene

- [ ] This was developed on a separate branch and is intended for **Squash and merge**.
- [ ] No Tailscale device IP/hostname, VIN, API key, access token, private location, or unredacted vehicle history was added.
- [ ] Any screenshots or generated assets were manually reviewed before committing.
- [ ] I described any effect on GitHub Actions, deployments, installers, or public releases.
