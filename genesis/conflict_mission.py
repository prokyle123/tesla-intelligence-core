"""GENESIS mission #1: explain conflicting charging and driving observations.

Offline, bounded, count-only diagnostic across five disjoint historical eras.
Observational evidence can suggest stale or semantically different signals;
it NEVER establishes the car charged while moving or alters classifications.
"""
from __future__ import annotations

from collections import Counter
import math

from .coverage import classify_regime, _finite

MAX_INTERVAL_S = 300.0
POWER_THRESHOLD_KW = 0.5
SPEED_THRESHOLD_KMH = 5.0
RUN_BINS = ("single", "2_to_4", "5_to_19", "20_plus")
REGIMES = ("DRIVING", "CHARGING", "PARKED_OR_OTHER", "UNKNOWN", "CONFLICT")

def _new_segment(previous: dict | None, current: dict) -> bool:
    if previous is None:
        return True
    try:
        interval = float(current["ts"])-float(previous["ts"])
    except (KeyError, TypeError, ValueError):
        return True
    return not (0 < interval <= MAX_INTERVAL_S)


def inspect_conflicts(eras: list[list[dict]]) -> dict:
    """Aggregate only, never include exact readings, times, vehicle identifiers."""
    if len(eras) != 5 or any(len(x) > 2400 for x in eras):
        raise ValueError("Five bounded source eras required.")
    era_reports = []
    overall_counts = Counter()
    overall_sources = Counter()
    overall_run_buckets = Counter()
    overall_transitions = Counter()
    overall_signal_disagreement = 0
    overall_conflicts = 0
    sampled = 0
    for index, rows in enumerate(eras, 1):
        counts, signal_types, bins, transitions = Counter(), Counter(), Counter(), Counter()
        current_run = 0
        previous = None
        previous_regime = None
        recent_regime = None
        for row in rows:
            if "ts" not in row:
                raise ValueError("Chronological telemetry timestamp required.")
            sampled += 1
            broken = _new_segment(previous, row)
            regime = classify_regime(row)
            counts[regime] += 1
            if broken:
                if current_run:
                    bins[_bucket(current_run)] += 1
                    current_run = 0
                recent_regime = None
            if regime == "CONFLICT":
                current_run += 1
                speed = _finite(row,"speed_kmh")
                charger = _finite(row,"charger_power_kw")
                charge_input = _finite(row,"charge_input_kw")
                charger_on = charger is not None and charger >= POWER_THRESHOLD_KW
                input_on = charge_input is not None and charge_input >= POWER_THRESHOLD_KW
                if charger_on and input_on:
                    signal_types["both_power_signals"] += 1
                elif charger_on:
                    signal_types["charger_power_only"] += 1
                elif input_on:
                    signal_types["charge_input_only"] += 1
                else:
                    signal_types["unclassified_power_signal"] += 1
                if charger is not None and charge_input is not None:
                    signal_types["both_power_signals_present"] += 1
                    if charger_on != input_on:
                        signal_types["signals_disagree_on_charging"] += 1
                if current_run == 1:
                    transitions[recent_regime or "ERA_OR_GAP_START"] += 1
            else:
                if current_run:
                    bins[_bucket(current_run)] += 1
                    current_run = 0
                    transitions["FOLLOWED_BY_"+regime] += 1
                recent_regime = regime
            previous = row
            previous_regime = regime
        if current_run:
            bins[_bucket(current_run)] += 1

        overall_conflicts += counts["CONFLICT"]
        overall_counts.update(counts)
        overall_sources.update(signal_types)
        overall_run_buckets.update(bins)
        overall_transitions.update(transitions)
        overall_signal_disagreement += signal_types["signals_disagree_on_charging"]
        era_reports.append({
            "era":index,
            "observations":len(rows),
            "conflicts":counts["CONFLICT"],
            "conflict_pct":round(100*counts["CONFLICT"]/len(rows),2) if rows else 0.0,
            "regime_counts":{key:counts[key] for key in REGIMES},
            "conflict_run_buckets":{key:bins[key] for key in RUN_BINS},
        })

    conflict_share = 100*overall_conflicts/sampled if sampled else 0
    if overall_conflicts < 30:
        mission = {
            "status":"LOW_CONFLICT_SIGNAL",
            "next_experiment":"Prioritize episode-level thermal forecasting rather than changing vehicle-state labels.",
        }
    elif overall_run_buckets["20_plus"] or overall_run_buckets["5_to_19"]:
        mission = {
            "status":"REVIEW_SIGNAL_SEMANTICS",
            "next_experiment":"Examine meaning and freshness of charging-power fields versus motion and charge-session state in a separate locally approved investigation.",
        }
    else:
        mission = {
            "status":"TEST_TRANSITION_STALENESS",
            "next_experiment":"Study time alignment around charge-start/stop and drive-start transitions before relabeling conflicts.",
        }
    return {
        "mission":"RESOLVE_SENSOR_CONTEXT",
        "status":"LOCAL_OBSERVATIONAL_DIAGNOSTIC",
        "observations":sampled,
        "conflicting_observations":overall_conflicts,
        "conflict_pct":round(conflict_share,2),
        "eras":era_reports,
        "power_signal_presence_in_conflicts":{
            "charger_power_only":overall_sources["charger_power_only"],
            "charge_input_only":overall_sources["charge_input_only"],
            "both_power_signals":overall_sources["both_power_signals"],
            "both_present":overall_sources["both_power_signals_present"],
            "power_indicators_disagree":overall_signal_disagreement,
        },
        "conflicting_run_length_buckets":{key:overall_run_buckets[key] for key in RUN_BINS},
        "start_context_counts":{key:overall_transitions[key] for key in
                                ("ERA_OR_GAP_START","DRIVING","CHARGING","PARKED_OR_OTHER","UNKNOWN","CONFLICT")},
        "end_context_counts":{key:overall_transitions["FOLLOWED_BY_"+key] for key in REGIMES},
        "selected_followup":mission,
        "vehicle_actuation":False,
        "production_changes":False,
        "cloud_uploads":False,
        "state_reclassification":False,
        "identifiers_included":False,
        "interpretation":"Power/speed overlap can reflect stale fields, differing field semantics or mismatched timestamps; do not conclude the vehicle charged while moving.",
    }

def _bucket(n: int) -> str:
    if n == 1:
        return "single"
    if n <= 4:
        return "2_to_4"
    if n <= 19:
        return "5_to_19"
    return "20_plus"
