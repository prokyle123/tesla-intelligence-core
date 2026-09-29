# Tesla Intelligence Core Companion — Android v0.4.0

Android companion for the Tesla Intelligence Core Raspberry Pi dashboard.

The package remains `com.ghost.tesla.mobile` for continuity with the original GHOST companion builds.

## v0.4.0

v0.4.0 is a companion-shell cleanup release focused on **navigation, connection state, Android safe areas and reliable dashboard rendering**.

### Native navigation that actually controls the dashboard

The bottom companion bar now switches dashboard sections directly instead of simulating clicks on the dashboard's web tabs.

```text
READY · EVENTS · NEURAL · TRUTH · THERMAL · MORE
```

The companion calls the dashboard's `switchView()` function directly and falls back to manipulating the active view in the DOM if that function is unavailable.

The selected native tab is highlighted, so a tap gives immediate visual feedback.

**MORE** includes:

- AI Lab
- Models
- Data Quality
- Sources
- Production
- History
- full-screen Neural Atlas
- Connection Center
- Tesla Browser Access
- connection diagnostics

### Clean connection header

The old single-row header was too cramped on phone-width screens.

v0.4.0 uses a two-row layout:

```text
TESLA INTELLIGENCE CORE                 TAILNET
100.x.x.x:8766 • LIVE            RETRY   SETUP
```

The connection-state button is reserved for meaningful states such as:

- `LOCAL`
- `TAILNET`
- `PUBLIC`
- `LOGIN`
- `VERIFY`
- `OFFLINE`

The app no longer turns an asynchronous JavaScript Promise into a fake `NO RENDER` / `{}` connection state.

### API connection and dashboard rendering are separate checks

The companion first proves that Tesla Intelligence Core is actually returning data from:

```text
/api/v3/overview
```

After that, it independently synchronizes the loaded dashboard views from:

```text
/api/status
/api/v3/overview
/api/v3/events
/api/v3/winter
/api/v4/neural/...
```

That distinction matters: a working network connection is not the same thing as a successfully rendered dashboard.

If a core endpoint has a problem, the companion can still keep the other dashboard sections alive instead of turning the entire app into a blank page.

### Connection Center

The Connection Center supports three routes:

```text
Local LAN
    ↓ fallback
Private Tailscale
    ↓ fallback
Public HTTPS / PIN gateway
```

Features include:

- **Auto-Find Pi on Local Network**
- scan of the current local /24 for dashboard port `8766`
- verification that a discovered host is actually Tesla Intelligence Core
- Local / Tailnet / Public probes run in parallel
- Local is preferred over Tailnet; Tailnet is preferred over Public
- remembered last successful route
- per-route diagnostics
- endpoint testing before saving
- manual **Open Public URL Anyway** fallback
- public PIN/login gateway recognition
- WebView session-cookie support after PIN login

### PIN gateway behavior

A Funnel login page returning HTTP 200 is **not** treated as dashboard data.

The companion verifies the actual dashboard API. If the public route requires authentication, it changes to:

```text
LOGIN
PIN gateway • enter PIN
```

After a successful PIN login, the WebView redirects back to the dashboard and the companion verifies the API again.

Do not put the PIN in source code, the GitHub repository or support logs.

### Android system UI

v0.4.0 keeps the app clear of modern Android system UI:

- status-bar / display-cutout insets
- bottom navigation-bar insets
- visible Android system controls instead of immersive mode
- safe-area reapplication when focus returns
- `adjustResize` for the setup keyboard
- phone-width two-row companion header

### Endpoint examples

Any endpoint can be left blank.

```text
Local:
http://192.168.x.x:8766

Private Tailnet:
http://100.x.x.x:8766

Public / Funnel:
https://your-public-hostname.example/
```

The public endpoint should terminate at the PIN gateway rather than intentionally exposing the raw dashboard.

## Tesla in-car browser

On the setup this project was developed with, the Tesla browser would not load the Pi's local/private dashboard URL. A working route was:

```text
Tesla browser
  -> public HTTPS Tailscale Funnel URL
  -> PIN gateway
  -> Tesla Intelligence Core dashboard
```

If the Pi has Internet access, Funnel is correctly configured, and the car has Internet access, this provides an Internet-reachable dashboard URL for the Tesla browser without exposing the raw dashboard directly.

Vehicle software, networking and installations can vary. See [the full Tesla browser guide](../../docs/TESLA_BROWSER.md).

## Build locally on Windows

With Android Platform Tools installed and USB debugging enabled:

```powershell
powershell -ExecutionPolicy Bypass -File .\Build-And-Install.ps1
```

The helper:

1. finds the physical USB Android device;
2. downloads Gradle 8.9 if needed;
3. builds the current source;
4. installs with `adb install -r`;
5. launches the app;
6. prints the installed package version.

A locally built APK normally keeps the same local Android debug signing key on that PC, which is useful when updating an existing locally built companion without losing saved endpoints.

## Public APK

The repository workflow builds a public debug-signed APK and attaches it to the current GitHub release.

A public debug-signed build is useful for sideloading/testing, but Android signatures can differ from APKs built on another machine. If an older local build has a different signature, Android will reject an in-place update.

A protected dedicated release-signing key is still the appropriate next step before treating the APK as a long-term production distribution channel.

## Diagnostics

Tap the connection-state button in the top-right of the companion header.

Diagnostics include:

- active route;
- last known good route;
- Local / Tailnet / Public probe results;
- current dashboard view;
- dashboard synchronization report;
- captured WebView JavaScript errors.

This is intended to make a blank or partially rendered dashboard diagnosable without guessing whether the problem is networking, authentication, API data or the WebView renderer.
