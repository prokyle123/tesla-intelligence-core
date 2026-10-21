# GHOST V2 — source reconciliation and release acceptance audit

**Audit date:** October 21, 2026  
**Target:** `v2.0.0` major stable release  
**Status:** **Release candidate source assembled; stable publish BLOCKED pending code merge + real install/upgrade/recovery validation.**

## What was inspected

- Operator-supplied, source-only, private `ghost-v2-source-review-redacted.zip` extracted for *review*, not uploaded to public GitHub.
- **99 source/service files** in that export, including a current running dashboard, read-only Tesla core, V3 intelligence server, V5 Tessie historical context, V6.2 memory collector, V6.4 claim guard, V6.6 briefing and the original watchdog.
- Recovered original V6/V6.1 pilot, V6.1 memory engine and passive thermal recorder from prior release packages because the exported source invoked those missing dependencies.
- The original installer/hardcoded watchdog path and service drop-ins were reviewed only; **not reused as a public migration**.

## Local source-candidate results

| Check | Result | Scope |
| --- | --- | --- |
| Python source compilation | PASS | Source candidate Python files |
| Candidate package contracts | **11 / 11 PASS** | Portable paths, missing assets, no inadvertent run on import, guarded rollback contract |
| Historical intelligence tests | **6 PASS** | V6.1 memory, V6.2 collector, V6.4 engine, V3 fallback, V5 Tessie and passive thermal recorder |
| Trip-shadow self-tests | **7 / 7 PASS** | Sequence, locations, outcomes, feedback, coverage, relationships and energy preview |
| Browser inline JS syntax | **12 / 12 PASS** | Dashboard and optional intelligence HTML |
| Sensitive-data pattern scan | **0 matches** | Project candidate source, tests, docs (regex coverage is not a full audit) |
| Installer read-only preflight | PASS | Source layout and generated systemd contents with a non-developer test account |
| GitHub main smoke CI | Existing smoke pipeline passing before source merge | Validates the current GitHub baseline, **not** V2 fresh installs |

The scanned ZIP source contained private-IP placeholders, which were replaced in the **candidate copy** with opt-in environment settings or private/loopback defaults. The Pi's own files were not modified. No VIN, private route, credentials, runtime SQLite records, GGUF model weights or executable `llama-server` binaries were intentionally included.

## What cannot be claimed yet

1. **The candidate has not yet been merged into the GitHub source tree.** Passing local tests on an unmerged ZIP does not mean the public installer contains Qwen3.5 4B, AI Insight, voice updates, or the memory/guard sidecars.
2. **No disposable Raspberry Pi clean install** of the complete V2 stack has been executed. The core v1 installer needs feature-preserving integration with the optional intelligence components and current dashboard.
3. **No production-safe v1→v2 upgrade/rollback** has been tested. The original one-off V6.6 installer contains developer-specific paths and must not replace the public installer.
4. **Model-runtime dependencies** and permissions: caller-provided llama.cpp, externally obtained Qwen3.5 4B model and a verified smaller fallback, limited Pi resources, correct service users/tailnet access.
5. **Unattended watchdog recovery/reboot** has not been tested against real model failure. Syntax and mock/logic checks alone cannot prove restart or rollback.
6. **Browser voice and cross-origin Intelligence UI** require tests from a phone, PC and Tesla browser; permissions and private/Tailscale binding must be clear. Do not publicly expose the direct AI endpoint.
7. **No calibrated pack-temperature interval promise:** the research-only V6.5.1 ambient predictor underperformed its simple baseline; it remains unpromoted.

## Publication contract

- `v1.0.0` remains the stable installable release.
- `v2.0.0-preview.1` is a truthful **feature preview**, not a complete installation.
- A full `v2.0.0` tag/release is permitted only once the code is actually merged, the installation/upgrade+rollback tests have passed on disposable hardware, privacy and provenance are reviewed, and the preflight + smoke workflow pass on the tagged commit.
- Until then, don't tell users to run an upgrade on an already-working GHOST Pi.

[Development integration PR](https://github.com/prokyle123/tesla-intelligence-core/pull/4) · [V2 requirements](V2_RELEASE_GATES.md) · [Feature matrix](FEATURE_MATRIX.md)
