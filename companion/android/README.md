# Tesla Intelligence Core Companion — Android v0.2.1

Android companion for the Tesla Intelligence Core Raspberry Pi dashboard.

The package remains `com.ghost.tesla.mobile` for continuity with the original GHOST companion builds.

## v0.2.1

- Adds **READY** and **EVENTS** as first-class quick-navigation buttons.
- Keeps Neural Engine, Truth Lab and Thermal History one tap away.
- Keeps the **MORE** sheet for AI Lab, Models, Data Quality, Sources, Production, History, full Neural Atlas, Tesla-browser access and diagnostics.
- Preserves Local → Tailnet → Public HTTPS failover and the PIN-gateway WebView session.

- Rebrands the shell as **Tesla Intelligence Core Companion**.
- Removes developer-specific IP addresses from fresh installs.
- Adds first-run endpoint setup.
- Tries **Local LAN → private Tailscale → optional public HTTPS** automatically.
- Adds the current dashboard views:
  - Home / Winter Readiness
  - Neural Engine
  - Truth Lab
  - Thermal History
  - AI Lab
  - Models
  - Data Quality
  - Sources
  - Events
  - Production
  - History
- Keeps the dedicated landscape Neural Atlas view.
- Keeps the S25/system-navigation fixes from v0.1.1.
- Keeps the Neural Atlas aspect-ratio fix from v0.1.2.
- Checks `/api/health`, `/health`, `/`, then TCP reachability.
- Adds diagnostics for every configured endpoint.
- Adds Tesla-browser access guidance and a public-URL copy button.
- Accepts WebView cookies so a PIN-gateway session can persist.
- Retests connectivity after returning from a longer background period.

## Endpoint order

```text
Local LAN -> private Tailnet -> optional public HTTPS
```

Any endpoint can be left blank.

```text
Local:   http://192.168.x.x:8766
Tailnet: http://100.x.x.x:8766
         http://hostname:8766
Public:  https://your-public-hostname.example/
```

The public endpoint should terminate at the PIN gateway rather than intentionally exposing the raw dashboard.

## Tesla in-car browser

On the setup this app was developed with, the Tesla browser would not load the Pi's local/private dashboard URL. A working route was:

```text
Tesla browser
  -> public HTTPS Tailscale Funnel URL
  -> PIN gateway
  -> Tesla Intelligence Core dashboard
```

Vehicle software, networking and installations can vary. See [the full Tesla browser guide](../../docs/TESLA_BROWSER.md).

## Build locally on Windows

With Android Platform Tools installed and USB debugging enabled:

```powershell
powershell -ExecutionPolicy Bypass -File .\Build-And-Install.ps1
```

The helper downloads Gradle 8.9 when needed, builds the debug APK, installs it over ADB and launches it.

## Public APK

The repository workflow builds a public debug-signed APK and attaches it to the current GitHub release.

A public debug-signed build is useful for sideloading/testing, but Android signatures can differ from APKs built on another machine. If an older local build has a different signature, it may need to be uninstalled once before the GitHub APK can be installed.

A protected dedicated release-signing key is the appropriate next step before treating the APK as a long-term production distribution channel.
