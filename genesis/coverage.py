"""Local-only evidence coverage diagnostics.

Counts only. No VIN, car IDs, locations, precise timestamps or raw samples are
returned. Even these counts are PRIVATE TO THE USER and must never be uploaded
to a fleet coordinator without a separate verified privacy protocol.
"""
from __future__ import annotations

from collections import Counter
import math

from .research import _thin
from .source import ALLOWED_METRICS

REGIMES = ("DRIVING", "CHARGING", "PARKED_OR_OTHER", "UNKNOWN", "CONFLICT")
DRIVE_THRESHOLD_KMH = 5.0
CHARGE_THRESHOLD_KW = .5


def _finite(row: dict, name: str) -> float | None:
    try:
        value = float(row.get(name))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def classify_regime(row: dict) -> str:
    """Conservative observational classification, never an asserted vehicle state.

    Drive/charging conflict is explicit. A missing signal must not be treated
    as evidence the vehicle was parked. Charging indicates power evidence,
    not a verified charge-session label or specific charger type.
    """
    speed = _finite(row, "speed_kmh")
    charge_signals = (_finite(row, "charger_power_kw"),
                      _finite(row, "charge_input_kw"))
    valid_charge = [x for x in charge_signals if x is not None]
    charge = max(valid_charge) if valid_charge else None
    moving = speed is not None and speed >= DRIVE_THRESHOLD_KMH
    charging = charge is not None and charge >= CHARGE_THRESHOLD_KW
    if moving and charging:
        return "CONFLICT"
    if moving:
        return "DRIVING"
    if charging:
        return "CHARGING"
    if speed is not None and charge is not None:
        return "PARKED_OR_OTHER"
    return "UNKNOWN"


def _counts(rows: list[dict]) -> dict[str,int]:
    counts = Counter(classify_regime(row) for row in rows)
    return {key: counts[key] for key in REGIMES}


def coverage_report(rows: list[dict], selected_pairs: list[tuple[str,str]] = ()) -> dict:
    """Compact local diagnostic; no sensor values, routes or times returned."""
    if len(selected_pairs) > 40:
        raise ValueError("Too many diagnostic candidate pairs.")
    for feature,target in selected_pairs:
        if feature not in ALLOWED_METRICS or target not in ALLOWED_METRICS:
            raise ValueError("Disallowed diagnostic signal.")
    sampled = _thin(rows)
    measures = {
        k: sum(_finite(r, k) is not None for r in sampled)
        for k in ALLOWED_METRICS
    }
    pairs = []
    for feature,target in selected_pairs:
        eligible = [r for r in sampled
                    if _finite(r,feature) is not None and _finite(r,target) is not None]
        pairs.append({
            "feature":feature,
            "target":target,
            "paired_samples":len(eligible),
            "paired_regime_counts":_counts(eligible),
        })
    raw_counts = _counts(rows)
    thin_counts = _counts(sampled)
    warnings = []
    if len(sampled) < max(1,len(rows)//4):
        warnings.append("TIME_THINNING_DISCARDS_MOST_SOURCE_SAMPLES")
    if sum(thin_counts[k] for k in ("DRIVING","CHARGING","PARKED_OR_OTHER")) == 0:
        warnings.append("NO_UNAMBIGUOUS_ACTIVITY_CONTEXT")
    if thin_counts["UNKNOWN"] or thin_counts["CONFLICT"]:
        warnings.append("INCOMPLETE_OR_CONFLICTING_ACTIVITY_SIGNALS")
    active = [k for k in ("DRIVING","CHARGING","PARKED_OR_OTHER") if thin_counts[k]>=30]
    if len(active) < 2:
        warnings.append("SINGLE_REGIME_DOMINATES_USABLE_EVIDENCE")
    return {
        "scope":"LOCAL_PRIVATE_COUNTS_ONLY",
        "raw_rows":len(rows),
        "thinned_rows":len(sampled),
        "sample_retention_pct":round(100*len(sampled)/len(rows),2) if rows else 0.0,
        "raw_regime_counts":raw_counts,
        "thinned_regime_counts":thin_counts,
        "thinned_metric_non_null_counts":measures,
        "candidate_pair_coverage":pairs,
        "warnings":warnings,
        "raw_values_included":False,
        "can_publish_to_fleet":False,
    }
