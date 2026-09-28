# Real-world use cases

Tesla Intelligence Core is built for the situations where a live battery percentage alone is not enough.

It is especially relevant to **cold-weather Tesla owners, long-distance daily commuters, Level 1 / slow-charging households, outdoor parking, irregular schedules, and anyone interested in self-hosted EV telemetry and predictive battery analytics**.

## Long winter commuting

A long commute changes the question from:

> What is my SOC right now?

to:

> What will the pack temperature and SOC look like when I leave, and what reserve is likely to remain when I arrive?

Tesla Intelligence Core combines learned trip behavior, thermal state, charging history, departure timing and forward forecasts so those pieces can be viewed together.

Useful signals include:

- projected departure SOC;
- projected arrival SOC reserve;
- future pack-temperature forecasts;
- cold-soak evidence;
- outside-air context;
- learned departure timing;
- model confidence / evidence quality.

## Level 1 and slow home charging

When charging power is limited, time becomes part of the energy problem.

A Level 1 connection may spend many hours adding energy, and cold-weather vehicle loads can make the relationship between wall input and battery gain more interesting than a simple "plugged in / not plugged in" indicator.

Tesla Intelligence Core tracks and learns:

- charging rate behavior;
- Level 1 charging evidence;
- charge-deadline context;
- wall input where available;
- derived pack / non-pack power context;
- departure SOC projection.

This is useful for people who cannot simply assume a high-power home charger will erase a charging deficit before morning.

## Outdoor parking and cold soak

Cold weather affects more than range.

Tesla Intelligence Core keeps thermal history and event evidence so the dashboard can reason about:

- pack cooling;
- thermal retention;
- cold-soak events;
- module temperature spread;
- outside temperature;
- future pack temperature;
- thermal margin at departure.

The objective is not to claim a universal battery model. It is to accumulate evidence from the specific car being observed.

## Irregular departure times

A fixed schedule works until life does not.

The departure learner uses real drive starts and is designed to distinguish a recurring routine from secondary/random trips. A configured departure time can seed learning, but it fades as actual history grows.

The dashboard keeps two concepts separate:

- **schedule confidence** — how strongly a recurring routine has been learned;
- **next-trip confidence** — how confident the system is about the immediate upcoming departure window.

## Tight arrival reserve

For longer drives, departure SOC is only half the story.

Tesla Intelligence Core can combine learned trip behavior and SOC forecasts into an expected **arrival reserve**, which is more useful operationally than only displaying the current state of charge.

## People who want auditable ML

The project deliberately exposes more of the model lifecycle than a typical consumer dashboard:

- classical ML baseline models;
- PyTorch GRU temporal models;
- serving and challenger generations;
- Truth Lab prediction resolution;
- promotion gates;
- governor state;
- rollback-oriented model management.

The goal is to make the prediction system inspectable rather than presenting an unexplained AI number.

## Self-hosted Tesla / EV analytics

Runtime history and learned model artifacts live on the user's own machine by default.

This makes the project a fit for people interested in:

- Raspberry Pi Tesla projects;
- self-hosted EV telemetry;
- TeslaMate extensions;
- Tessie-based analytics;
- battery thermal monitoring;
- charging analytics;
- time-series forecasting;
- home-lab vehicle intelligence.

## What it does not do

Tesla Intelligence Core is currently **read-only**.

It does not intentionally send vehicle commands for driving, locking, charging, climate control or other vehicle operation.

Predictions are estimates, not guarantees or safety-critical instructions.
