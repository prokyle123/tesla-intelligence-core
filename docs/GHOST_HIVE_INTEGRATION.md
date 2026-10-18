# GHOST Hive integrated tab — release preview

Home, Winter Readiness, AI Lab, Neural Engine, current filters and prediction models are preserved.
The current product patch changes exactly two existing files: one navigation link in web/templates/index.html, and two Blueprint-registration lines in ghost_tesla_ai/server.py. Two new files are added: ghost_tesla_ai/hive_local.py and web/templates/hive.html.

## Real numbers, not mock data

- Local resolved predictions are counted from GHOST prediction_audit, NOT telemetry rows.
- Temperature accuracy is percentage of resolved battery_temp_c predictions within ±2°F of measured temperature.
- Mean absolute error is the resolved pack-temperature error converted from Celsius to Fahrenheit by multiplying by 1.8.
- The monthly and daily charts show GHOST's actual locally scored predictions.
- Fleet contributors, worldwide accuracy, country totals, regions and actual received uploads remain unknown until verified central Hive evidence is connected.
- Decorative earth/world artwork never represents a real individual's location.
- All local telemetry queries use read-only SQLite and expose no VIN, GPS, raw trip or identifying car ID.

## Consent and transport

The Hive information banner is actionable: it explains the future participation contract in a dialog. It does NOT enable sharing. Real uploads remain OFF, no new Tessie polling, timers or fleet transfer services are started. The separate current coordinator/transfer prototype only supports manual synthetic trials and is not yet anonymous or privacy-reviewed for real data.

## Guarded non-destructive live deployment

Do not run the feature-branch full installer against a customized GHOST installation; it can overwrite local changes. Use scripts/ghost_hive_integrate.py instead.

Read-only precheck:

    python3 scripts/ghost_hive_integrate.py --root /opt/ghost-tesla-ai --backup /home/ghost/ghost-hive-integration-backups --check

Only after reviewing success, apply as a user with write permission (sudo may be required):

    sudo python3 scripts/ghost_hive_integrate.py --root /opt/ghost-tesla-ai --backup /home/ghost/ghost-hive-integration-backups --apply

The apply action backs up touched files byte-for-byte (private 0700 directory), rejects unfamiliar code patterns or existing Hive modifications, syntax-checks server changes and does not automatically restart services. A separate operator web-only service restart and local endpoint checks are required.

Checked rollback:

    sudo python3 scripts/ghost_hive_integrate.py --root /opt/ghost-tesla-ai --backup /home/ghost/ghost-hive-integration-backups --rollback

Restart only the web service after rollback. The rollback refuses to overwrite any post-install changes.

## Remaining implementation

Central authenticated Hive ingest and analytics connected to each GHOST instance; reviewed explicit consent and revocation; securely verified real-data aggregate upload; coarse optional region handling; real-world visual QA on mobile and desktop; monitored rollout and reliable updates. No stage may claim a global accuracy figure without real cohort evidence.