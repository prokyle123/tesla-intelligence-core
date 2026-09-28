# FAQ

## Is this an official Tesla project?

No. Tesla Intelligence Core is an independent enthusiast project and is not affiliated with or endorsed by Tesla.

## Does it control the car?

No. The project is currently read-only by design. It observes telemetry and builds predictions.

## What is the main goal?

To turn live + historical Tesla telemetry into useful forward-looking context: expected departure, battery thermal state, charging readiness, projected arrival reserve and related confidence/evidence.

## Why does it need time to learn?

Some information cannot be known from one snapshot.

Examples:
- normal departure timing;
- cold-soak behavior;
- real charge-rate behavior;
- typical commute SOC use;
- neural sequence patterns.

The dashboard intentionally shows when evidence is still thin.

## Do I need Tessie?

No.

Supported public installer paths:
- Tessie API;
- TeslaMate MQTT.

Tessie is convenient because historical backfill can bootstrap learning immediately.

## What does the departure seed do?

It is a fading prior.

If you enter `06:00`, the learner can use that as initial context. As real drive history accumulates, the configured prior loses influence.

It is not intended to force every future prediction to 06:00.

## What happens with random trips?

Random/secondary trips remain useful evidence, but the departure learner is designed so occasional drives do not dominate a repeated routine.

## Why can readiness be below 100 when the car looks fine?

Readiness includes evidence quality and projected conditions, not only live SOC.

The **Winter Readiness Limiters** are meant to show exactly what is costing points.

## Is the readiness score model accuracy?

No.

Readiness is an operational score. Neural/classical model metrics and Truth Lab evidence are separate.

## Can I use a Raspberry Pi 4?

Possibly, but Pi 5 is recommended. Live collection/dashboard work is light relative to neural training.

## Where is my data stored?

Main runtime data:

```text
/var/lib/ghost-tesla-ai
```

Config/secrets:

```text
/etc/ghost-tesla-ai
```

## Can I expose the dashboard to the Internet?

The project includes an optional Tailscale Funnel + PIN gateway workflow, but public exposure should be treated carefully.

Read:
- [Security](../SECURITY.md)
- [Remote access](REMOTE_ACCESS.md)

## Why do internal names still say GHOST?

Tesla Intelligence Core is the public project name. Internal package/service identifiers such as `ghost_tesla_ai`, `ghost-ai` and `ghost-tesla-ai-*` are retained for compatibility with existing installations.

## How do I report another Tesla model working?

Open a compatibility issue and follow [Compatibility](COMPATIBILITY.md).
