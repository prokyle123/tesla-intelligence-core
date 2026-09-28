# Tesla in-car browser access

Tesla Intelligence Core is a web dashboard, so the useful question is not only whether the Pi is online — it is whether the **Tesla browser can reach the URL you give it**.

## Why this project uses a public HTTPS option

On the setup this project was developed with, the Tesla in-car browser would **not** load the Raspberry Pi dashboard through its local/private address, even though phones and computers on the appropriate network could.

The working route was:

```text
Tesla browser
     |
     | Internet HTTPS
     v
Tailscale Funnel public URL
     |
     v
PIN gateway on the Pi (:8777)
     |
     v
Tesla Intelligence Core dashboard (:8766)
```

Your vehicle software, network and installation may behave differently. This is one tested way to make the dashboard usable from the in-car browser when a local/private URL is not usable there.

## Why the PIN gateway matters

Tailscale Funnel makes an HTTPS service reachable from the public Internet.

The intended path is therefore:

```text
Funnel -> PIN gateway -> dashboard
```

not:

```text
Funnel -> raw dashboard
```

The PIN gateway prevents the intended public route from directly exposing the raw dashboard without an authentication step.

## Example setup

Set the PIN locally on the Pi:

```bash
cd /opt/ghost-tesla-ai
./venv/bin/python -m ghost_tesla_ai.funnel_pin_setup
```

Start the gateway:

```bash
sudo systemctl enable --now ghost-tesla-ai-funnel-gateway.service
```

Point Funnel at the gateway:

```bash
sudo tailscale funnel --bg http://127.0.0.1:8777
```

Verify the local gateway and Funnel state:

```bash
curl -I http://127.0.0.1:8777/
tailscale funnel status
```

Then open the HTTPS Funnel URL in the Tesla browser and enter the PIN.

## What this gives you in the car

When the Pi installation has working Internet access and the Funnel/gateway are healthy, the Tesla browser can reach the dashboard whenever the car also has Internet connectivity.

That makes the in-car browser useful for the same live views available elsewhere:

- Winter Readiness;
- departure and arrival SOC planning;
- pack-temperature forecasts;
- Neural Engine / Neural Atlas;
- Truth Lab;
- Thermal History;
- charging and thermal power-path context;
- Models, Data Quality, Sources, Events, Production and History.

## Security notes

- Treat the Funnel hostname as Internet-visible once shared.
- Keep the PIN private.
- Do not publish `funnel_pin.json`.
- Do not point public Funnel traffic straight at the raw dashboard port if you expect PIN protection.
- Private Tailscale remains the better path for phones/computers that can join your tailnet.
- Tesla browser behavior can vary with vehicle software and network conditions; this guide documents the project's tested setup rather than claiming every car behaves identically.

## Android companion

The Android companion is a separate convenience layer for phones/tablets.

It can try:

```text
Local LAN -> private Tailnet -> optional public HTTPS
```

So the phone can use the fastest/private path available, while the Tesla browser can use the optional public HTTPS path when local/private URLs are not usable there.

See [Companion Android app](../companion/android/README.md).
