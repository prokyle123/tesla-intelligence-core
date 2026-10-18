# GHOST HIVE v1 — private and public dashboards

## What is implemented

The original GHOST Home tab is unchanged. The extra /hive tab is a full-width
dark blue/cyan responsive dashboard built as actual HTML, CSS, and JavaScript.
It follows the approved screenshot's nine-panel layout: NASA Earth globe hero,
four KPIs, contributor growth, prediction quality, battery temperature error,
global region map, research activity, top regions, and privacy controls.
There are no middle-page banners or additional navigation bars.

The top-right private "Your Contribution" card is now the ONLY consent entry
point; the owner can join, switch off or revoke/delete from its modal. Those
POST actions are available only across the existing authenticated SSH-local
tunnel during this development preview. No browser token copy-paste.

Both private and public web pages use the same layout and color vocabulary.
The public page is read-only: no modal, no enrollment routes, no owner keys,
and no links to private GHOST APIs. No fictional contributor count, accuracy,
regions, or location hotspots are displayed.

## Real values, honest missing-data

Private page: GET /api/hive/local reads read-only GHOST prediction_audit data
and coordinator's already-public cohort summary. Local completed predictions,
local within-2F percent and local temperature MAE are real. The network bar
chart is shown only for monthly groups that meet release privacy criteria.

Public page: docs/hive/index.html reads ONLY network.json (ghost-hive-public-v1).
Current six-field monthly research protocol has no fleet within-2F accuracy
histogram, GPS, exact trip locations, countries, or validated regional data.
These fields remain unavailable until separately consented, researched,
and implemented. Do not confuse MAE with percent of forecasts within ±2F.
Total enrolled reporting installation count may start at 1; months with fewer
than 10 reporting installations suppress cohort details, without blocking
real consent or ingestion. Enrollment does NOT verify unique human owners.

Graphic assets are decorative; no bright dots represent contributor sites.
Earth image: NASA Goddard Black Marble 2016 (NASA SVS 30878), photo illustration (nasa.gov/JPL). World base
map: CC0 Blank world map Equal Earth / Natural Earth (Wikimedia Commons).
The page retains its built-in SVG fallback when those external assets fail.
Before final production, download, optimize and bundle these static
graphic resources locally to avoid third-party image requests.

## Preview the sanitized PUBLIC webpage on the Ghost Pi

After updating reviewed development source to its pinned SHA and the existing
coordinator is running, from normal Ghost SSH user:

    bash ~/genesis-product-source/scripts/hive_public_preview.sh start
    bash ~/genesis-product-source/scripts/hive_public_preview.sh status
    bash ~/genesis-product-source/scripts/hive_public_preview.sh refresh
    bash ~/genesis-product-source/scripts/hive_public_preview.sh stop

This exports a snapshot from the private hub SQLite, verifies an exact
allowlist and publishes only index.html and network.json in an isolated
0700 static directory. Python http.server binds ONLY to 127.0.0.1:8780.
No private files, authentication credentials, raw records or GHOST ports
are mounted as part of the static document root.

Windows PowerShell viewing tunnel (leave open):

    ssh -N -L 127.0.0.1:8780:127.0.0.1:8780 ghost@YOUR_GHOST_TAILSCALE_IP

Open http://127.0.0.1:8780/ in a separate tab.
Optional one-time refresh timer setup (does not enable contributor consent):

    sudo bash ~/genesis-product-source/scripts/hive_public_refresh_timer.sh install

The timer refreshes the PUBLIC sanitized snapshot hourly. It never sends
your own vehicle data anywhere or changes the existing GHOST models.

## Publish with GitHub Pages

Workflow: .github/workflows/hive-public-pages.yml deploys only two files
(index.html and network.json), after running the strict snapshot validator.
Enable Settings → Pages → Source: GitHub Actions on the repository.
Once the workflow is on main, run Hive Public Analytics via Actions to deploy.
Expected site address follows GitHub Pages convention:
    https://prokyle123.github.io/tesla-intelligence-core/
Do not claim the public URL is active until Pages deployment confirms it.

Initially GitHub Pages uses a committed zero-data placeholder JSON.
For AUTOMATIC real updates, configure repository variable HIVE_PUBLIC_FEED_URL
to a separately reviewed public HTTPS endpoint that serves ONLY the sanitized
ghost-hive-public-v1 JSON. Never point it at GHOST Home, Hive port 8778,
or a URL containing bearer tokens. Hourly Actions runs fetch and validate
the feed; failed validation stops publication without revealing data.

The current coordinator is loopback-only and no public HTTPS feed is
configured. Production hosting still needs an approved transport
(e.g. a narrow static-only HTTPS proxy) and operator go-live approval.

## Private Hive UI scoped update

Use reviewed branch scripts/ghost_hive_update.py --check and --apply against
the customized live /opt/ghost-tesla-ai. The installer updates ONLY
ghost_tesla_ai/hive_local.py and web/templates/hive.html, and checks
known previous hashes. It does NOT overwrite Home or Classic models.
A private backup under a fresh directory must be retained for rollback.
Restart only ghost-tesla-ai-web.service, not collector or trainer.

## Security limitations and next protocol versions

Coordinator sees individual monthly aggregate contributions and associates
them with enrollment credentials. The resulting transfer is pseudonymous,
not fully anonymous nor secure aggregation. Reported installation counts
are not validated unique humans. Advanced fleet statistics, weather zones
and region heat maps require separate affirmative location consent and
privacy suppression before implementation. Neural weights remain local.
