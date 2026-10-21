# GHOST Intelligence V2 — guarded local language-model integration

**Status: release candidate under integration; not part of the public v1.0 installer.**
This document describes an observed development installation on a Raspberry Pi 5 as of October 20, 2026. It is not evidence that all features are present or supported on other installations.

[Project overview](../README.md) | [V2 release gates](V2_RELEASE_GATES.md) | [v1 architecture](ARCHITECTURE.md)

## What is actually running on the development Pi

On October 20, the operator verified Qwen3.5 4B Q4_K_M running as the **guarded production narration model**, with the Tesla collector, dashboard and background training services still running. A model-backed briefing passed the evidence gate. One watchdog invocation passed after a misconfigured path was repaired; this is **not** a tested full-failure recovery. A longer production soak has not yet completed.

| Component | Role | Development evidence | Public release state |
| --- | --- | --- | --- |
| Core Tessie/TeslaMate telemetry | Read-only source of Tesla state, charging and thermal observations | Collector active on Pi | Shipped in v1 |
| Winter readiness & predictive models | Current/next-departure scores, forecasts, independent training | Existing production service preserved | v1 components; newer live UI needs source reconciliation |
| GHOST Intelligence V3/V5 | Cached local narration, historical Tessie comparisons, guarded sensor descriptions | Local intelligence server and collector | **Not installed by public v1 setup** |
| Verified memory V6.2 | Hourly observation journal; retrieved context, no language-model weight updates | Timer active | **Not yet packaged portably** |
| V6.4.4a evidence checks | Validate numbers, pack changes and claims about baselines | Offline tests + production canary | **Not yet packaged portably** |
| Qwen3.5 4B V6.6 | Optional asynchronous long-form interpretation | Production canary accepted a real briefing | **Not yet enabled on fresh installs** |
| Browser voice / rule alerts | Verified hourly speech and immediate sensor/rule notifications | Present on developer dashboard | Needs complete current dashboard source reconciliation |
| V6.5/V6.5.1 ambient thermal models | Read-only exploratory numerical thermal evaluation | 340 qualified windows across scenarios; 18 charging days | Research only; **not in readiness or alerts** |

## Three separate kinds of “AI”

1. **Trained numerical predictors:** learned trip, charge and thermal targets are trained and governed independently. A new model generation is not automatically selected as production.
2. **Evidence and historical memory:** verified observations and qualified comparisons are selected from read-only Tesla history and an independent memory journal. A sample count is not automatically an independent-day count.
3. **Local language model:** Qwen3.5 4B composes optional explanations of that evidence. It **does not train itself on conversations or automatically update its model weights**. A validator checks claims; rejected prose is replaced by deterministic verified text.

There is no Tesla control path: no start/stop charging, HVAC commands, driving commands, door locks, or other write calls.

## Runtime data flow (development implementation)

```text
Tessie/TeslaMate -> existing read-only collector -> local telemetry DB
                         |                                |
                         v                                v
                 governed ML/GRU models        read-only historical comparison
                         |                                |
                         v                                v
              verified readiness data       V6.2 verified memory + V5 sensors
                         |                                |
                         +---------------+----------------+
                                         |
                               structured evidence
                                         |
                       guarded optional Qwen3.5 4B inference
                                         |
                         claim / numerical / relationship checks
                                /                   \
                         accepted prose      verified-text fallback
                                \                   /
                              local cached AI briefing
                                         |
                            dashboard narration and voice
```

**Boundaries:** Fast anomaly alerts and top-of-hour browser speech are not scheduled through Qwen's ~1–3-minute inference path; those paths must remain responsive if Qwen is down. Readiness predictions, database records, and source fields are never replaced by generated prose.

## Model-runtime requirements

- Raspberry Pi 5 8 GiB tested; 4B has meaningful RAM/swap cost. CPU inference during early trials took roughly 1–3 minutes, varying by response.
- 4B requires an independently sourced compatible GGUF file and an appropriate build of llama.cpp. **Model weights and binary artifacts are not checked into this GitHub repository.**
- The 4B server binds to loopback, not a public interface, and substitutes for 0.6B rather than running alongside it.
- A background briefing timer generates cached prose approximately hourly; it is not recomputed on dashboard refresh.
- A watchdog and verified rollback are mandatory before any operator opts in. A health probe alone does not prove all failure-recovery cases.
- Cached narration can be older than live telemetry; the UI must distinguish timestamped AI commentary from current verified readings.

## What remains unqualified

The 90-day V6.5 read-only audit yielded **247 passive-charging windows on 18 distinct days**, 68 unplugged windows on 11 days and 25 charge-complete windows on 4 days. Charging coverage does not yet meet the 20-day gate. In an exploratory chronological charging holdout, the ambient-context predictor had ~1.419°F day-balanced MAE versus ~1.215°F for the simple baseline, so **no ambient model, uncertainty band or anomaly promotion is warranted**.

The 4B narrative's claim checks were developed against real and synthetic cases, but are not a guarantee of factuality. Relative claims such as “1.8°F equals the 0.9°F median” were caught and fixed in later guard versions. We must keep recording acceptance/fallback reasons and check actual prose.

## Source/release reconciliation needed

The developer's installed code spans two installations plus separately generated memory, voice and research components. The public v1 installer does not recreate that state. In particular the original V6.6 canary contains developer-local paths, source-hash assumptions, a microSD-only prerequisite and a watchdog unit path mismatch that required a manual repair.

**Do not copy that one-off installer verbatim into the public update script.** Rebuild it around configurable users, paths, independent optional installation, explicit source/state checks, a model license and download plan, idempotent systemd templates, recovery tests, and a separate secret/privacy review. The existing public installer must retain conservative upgrade behavior until integration is verified.

For a read-only, content-free overview of what exists on a Pi:

```bash
python3 scripts/v2_release_inventory.py --json
```

It prints service states and source-file SHA-256 fingerprints, not telemetry, full source, tokens, routes or model weights. It is not a deploy or an acceptance test.

## User-facing release promise — only after gates pass

An **optional**, locally hosted intelligence layer that explains verified battery charging and winter-readiness observations using history; preserves deterministic fallback and immediate alerts; exposes limitations; and can be installed, updated, repaired and completely disabled without harming core learning, historical databases or dashboard operation.

See [V2 release gates](V2_RELEASE_GATES.md) before tagging.
