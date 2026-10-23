"""M1 retrospective evidence audit. No mutation, networking or model promotion.

Cross-checks previously selected shadow hypotheses in an OLDER, nonoverlapping
window. This is historical repeatability, not prospective confirmation.
The service never uploads raw observations and reports metadata only.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .research import _linfit, _mae, _thin
from .source import ALLOWED_METRICS
from .coverage import classify_regime, coverage_report

PAIRS_LIMIT = 40
MIN_EVIDENCE = 180
FOLDS = (0.45, 0.55, 0.65)
FOLD_WIDTH = 0.10
EMBARGO = 10
MIN_GAIN = 0.10

KNOWN_COUPLINGS = {
    ("pack_current_abs_a", "pack_power_kw"): "Direct electrical power/current coupling; not a new physical discovery.",
    ("speed_kmh", "pack_current_abs_a"): "Driving state and vehicle load can confound this association.",
    ("outside_temp_c", "battery_temp_c"): "Expected ambient-to-pack thermal coupling; slow dynamics not tested.",
    ("charger_power_kw", "pack_current_abs_a"): "Charging regime confounds charging power with pack current.",
}
TREND_SENSITIVE = {
    ("outside_temp_c", "battery_level"),
    ("battery_temp_c", "battery_level"),
}

def _forward_folds(pairs: list[tuple[float, float]]) -> list[float]:
    n = len(pairs)
    if n < MIN_EVIDENCE:
        return []
    out = []
    for fraction in FOLDS:
        stop = int(n * fraction)
        start_test = stop + EMBARGO
        stop_test = min(n, int(n * (fraction + FOLD_WIDTH)))
        train, test = pairs[:stop], pairs[start_test:stop_test]
        if len(train) < 70 or len(test) < 15:
            return []
        slope, intercept = _linfit(train)
        baseline_center = statistics.fmean(y for _, y in train)
        baseline = _mae(test, lambda x: baseline_center)
        fitted = _mae(test, lambda x: slope*x + intercept)
        if not all(math.isfinite(v) for v in (baseline, fitted)) or baseline < 1e-7:
            return []
        out.append(100*(baseline-fitted)/baseline)
    return out

def _differences(rows: list[dict], feature: str, target: str) -> list[tuple[float,float]]:
    """Delta controls require adjacent samples, stable regime and <=30 min gap.

    Subtracting distant driving/charging sessions can manufacture apparent
    evidence. UNKNOWN/CONFLICT regimes cannot establish a continuous state.
    """
    out = []
    for prior, current in zip(rows, rows[1:]):
        dt = float(current["ts"]) - float(prior["ts"])
        regime = classify_regime(current)
        if not 0 < dt <= 1800 or regime not in ("DRIVING", "CHARGING", "PARKED_OR_OTHER"):
            continue
        if classify_regime(prior) != regime:
            continue
        out.append((float(current[feature])-float(prior[feature]),
                    float(current[target])-float(prior[target])))
    return out

def audit_pair(older_rows: list[dict], feature: str, target: str) -> dict:
    if feature not in ALLOWED_METRICS or target not in ALLOWED_METRICS or feature == target:
        raise ValueError("Unapproved metric pair for research.")
    spaced = _thin(older_rows)
    matched = [r for r in spaced if r.get(feature) is not None and r.get(target) is not None]
    pairs = [(float(r[feature]),float(r[target])) for r in matched]
    gains = _forward_folds(pairs)
    delta_pairs = _differences(matched, feature, target)
    diff_gains = _forward_folds(delta_pairs)
    grouped = {
        key: [r for r in matched if classify_regime(r) == key]
        for key in ("DRIVING","CHARGING","PARKED_OR_OTHER","UNKNOWN","CONFLICT")
    }
    strata = {
        key: _forward_folds([(float(r[feature]),float(r[target]))
                             for r in grouped[key]])
        for key in ("DRIVING","CHARGING","PARKED_OR_OTHER")
    }
    passed = len(gains) == len(FOLDS) and all(g >= 100*MIN_GAIN for g in gains)
    improving_regimes = [key for key, group in strata.items()
                         if len(group) == len(FOLDS) and all(v >= 100*MIN_GAIN for v in group)]
    tested_regimes = [key for key,group in strata.items() if group]
    mechanism = KNOWN_COUPLINGS.get((feature,target))
    warnings = []
    if mechanism:
        warnings.append("EXPECTED_OR_CONFOUNDED_RELATIONSHIP")
    if (feature,target) in TREND_SENSITIVE:
        warnings.append("TIME_AND_CHARGING_CONFOUNDING_LIKELY")
    if len(delta_pairs) < MIN_EVIDENCE:
        warnings.append("INSUFFICIENT_CONTIGUOUS_DELTA_EVIDENCE")
    if not diff_gains or min(diff_gains) <= 0:
        warnings.append("FIRST_DIFFERENCE_NOT_CONFIRMED")
    if grouped["UNKNOWN"] or grouped["CONFLICT"]:
        warnings.append("AMBIGUOUS_REGIME_CONTEXT")
    if len(tested_regimes) < 2:
        warnings.append("INSUFFICIENT_CROSS_REGIME_EVIDENCE")
    elif not improving_regimes:
        warnings.append("NO_ROBUST_WITHIN_REGIME_SUPPORT")
    if not gains:
        status = "INSUFFICIENT_HISTORICAL_EVIDENCE"
    elif passed:
        status = "HISTORICALLY_REPEATABLE"
    else:
        status = "NOT_REPEATED"
    return {
        "feature":feature, "target":target,
        "status":status, "older_samples":len(pairs),
        "folds_tested":len(gains),
        "fold_gains_pct":[round(v,2) for v in gains],
        "first_difference_folds_tested":len(diff_gains),
        "first_difference_gains_pct":[round(v,2) for v in diff_gains],
        "regimes_with_evidence":tested_regimes,
        "regime_paired_samples":{key:len(grouped[key]) for key in grouped},
        "contiguous_delta_pairs":len(delta_pairs),
        "regimes_with_consistent_gain":improving_regimes,
        "warnings":warnings,
        "interpretation":mechanism or "Unclassified exploratory association; do not infer causality.",
        "prospective_confirmation":False,
        "eligible_for_production":False,
        "publishable_fleet_finding":False,
    }

def retrospective_audit(rows: list[dict], selected_pairs: list[tuple[str,str]],
                        recent_window: int = 6000) -> dict:
    """Audit frozen candidate names against earlier, separate source rows.

    Not a true future holdout: those would require observations arriving
    AFTER candidate freeze. No raw samples or dates are returned.
    """
    if not 100 <= recent_window <= 12000:
        raise ValueError("Window out of supported bounds.")
    if len(selected_pairs) > PAIRS_LIMIT:
        raise ValueError("Too many candidate pairs for a bounded audit.")
    if len(rows) <= recent_window:
        older = []
    else:
        older = rows[:-recent_window]
    audited = []
    for feature,target in selected_pairs:
        audited.append(audit_pair(older,feature,target))
    return {
        "status":"RETROSPECTIVE_ONLY",
        "older_rows_inspected":len(older),
        "candidates_audited":len(audited),
        "historically_repeatable":sum(x["status"] == "HISTORICALLY_REPEATABLE" for x in audited),
        "prospectively_confirmed":0,
        "fleet_discoveries":0,
        "results":audited,
        "source_coverage":coverage_report(older,selected_pairs),
        "production_changes":False,
        "hivemind_uploads":False,
        "note":"Earlier historical records are a separate retrospective check, not future validation. Never promote results automatically.",
    }
