"""GENESIS Hypothesis Architect v0: constrained, self-directed research proposals.

This system *chooses* from an auditable family of safe hypothesis recipes and
selects next investigations based on evidence. It never synthesizes executable
code, alters production predictions, commands the car, or contacts any API.
Models below are *contemporaneous associations*, NOT future-time forecasts.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from .coverage import classify_regime
from .research import _linfit, _mae

TRAIN_BLOCKS = 3
TEST_BLOCKS = 2
MAX_TRIALS = 12
MIN_TRAIN = 75
MIN_TEST_PER_ERA = 12
MIN_TEST_TOTAL = 30
MIN_GAIN_PCT = 10
SAMPLE_GAP_S = 180

@dataclass(frozen=True)
class Recipe:
    question: str
    feature: str
    target: str
    regime: str
    caveat: str
    next_action: str

RECIPES = (
    Recipe("Can ambient temperature explain pack temperature while parked?",
           "outside_temp_c", "battery_temp_c", "PARKED_OR_OTHER",
           "EXPECTED_THERMAL_RELATIONSHIP",
           "Investigate delayed parked pack-temperature response with episode-based holdouts."),
    Recipe("Does ambient temperature explain pack temperature while charging?",
           "outside_temp_c", "battery_temp_c", "CHARGING",
           "EXPECTED_THERMAL_RELATIONSHIP",
           "Separate heater-on and heater-off charging episodes before inferring causality."),
    Recipe("Is driving speed informative about pack-current load?",
           "speed_kmh", "pack_current_abs_a", "DRIVING",
           "DRIVING_LOAD_CONFOUNDING",
           "Compare constant-speed driving segments and motor load after regime verification."),
    Recipe("Can charging power help explain pack current?",
           "charger_power_kw", "pack_current_abs_a", "CHARGING",
           "EXPECTED_ELECTRICAL_COUPLING",
           "Check pack voltage and charging AC/DC regimes before fitting detailed physics."),
    Recipe("Can pack-current magnitude explain pack power while driving?",
           "pack_current_abs_a", "pack_power_kw", "DRIVING",
           "EXPECTED_ELECTRICAL_COUPLING",
           "Check pack voltage and power sign; absolute current loses energy-flow direction."),
    Recipe("Does pack temperature explain module spread while parked?",
           "battery_temp_c", "module_temp_spread_c", "PARKED_OR_OTHER",
           "OBSERVATIONAL_ASSOCIATION",
           "Test against outside temperature and separately grouped cold-soak episodes."),
    Recipe("Does ambient temperature explain SOC while parked?",
           "outside_temp_c", "battery_level", "PARKED_OR_OTHER",
           "TIME_AND_CHARGE_CONFOUNDING",
           "Treat direct temperature-to-SOC correlation as suspect; control charging and seasonal behavior."),
    Recipe("Does pack temperature explain SOC during charging?",
           "battery_temp_c", "battery_level", "CHARGING",
           "TIME_AND_CHARGE_CONFOUNDING",
           "Control charge-session progress before treating battery temperature as informative."),
    Recipe("Can outside temperature explain pack temperature during driving?",
           "outside_temp_c", "battery_temp_c", "DRIVING",
           "EXPECTED_THERMAL_RELATIONSHIP",
           "Test pack heating after driving starts, with time-lagged episode grouping."),
    Recipe("Does pack temperature relate to current draw while driving?",
           "battery_temp_c", "pack_current_abs_a", "DRIVING",
           "LOAD_AND_THERMAL_CONFOUNDING",
           "Control road load and motor speed before attributing pack current to battery temperature."),
    Recipe("Can pack temperature explain cell-module spread while charging?",
           "battery_temp_c", "module_temp_spread_c", "CHARGING",
           "OBSERVATIONAL_ASSOCIATION",
           "Check thermal behavior separately during L1, high-power and preconditioning episodes."),
)

def _spaced(rows: list[dict], recipe: Recipe) -> list[tuple[float,float]]:
    # Space observations *within each chronological block*; never bridge eras.
    out = []
    last = -float("inf")
    for row in rows:
        if classify_regime(row) != recipe.regime:
            continue
        x, y, ts = row.get(recipe.feature), row.get(recipe.target), row.get("ts")
        if x is None or y is None or ts is None:
            continue
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(ts)):
            continue
        if ts < last + SAMPLE_GAP_S:
            continue
        out.append((float(x),float(y)))
        last = ts
    return out

def _status(result: dict) -> str:
    if result["status"] == "SHADOW_ASSOCIATION":
        return "TEST_LAGGED_CAUSAL_CONTROLS"
    if result["status"] == "INSUFFICIENT_EVIDENCE":
        return "COLLECT_REPRESENTATIVE_EPISODES"
    return "REFINE_OR_REJECT_HYPOTHESIS"

def evaluate_recipe(blocks: list[list[dict]], recipe: Recipe) -> dict:
    if len(blocks) != TRAIN_BLOCKS + TEST_BLOCKS:
        raise ValueError("Hypothesis Architect expects exactly five nonoverlapping eras.")
    samples = [_spaced(block,recipe) for block in blocks]
    counts = [len(x) for x in samples]
    train = [pair for era in samples[:TRAIN_BLOCKS] for pair in era]
    tests = samples[TRAIN_BLOCKS:]
    status = "INSUFFICIENT_EVIDENCE"
    gains = []
    baseline_mae = []
    model_mae = []
    reason = "Insufficient independent driving/charging/parked evidence in chronological training or test eras."
    if (len(train) >= MIN_TRAIN
            and min(len(x) for x in tests) >= MIN_TEST_PER_ERA
            and sum(len(x) for x in tests) >= MIN_TEST_TOTAL):
        if len({round(x, 6) for x,_ in train}) < 3:
            status = "INSUFFICIENT_EVIDENCE"
            reason = "Training feature lacks meaningful variation."
        else:
            slope, intercept = _linfit(train)
            center = statistics.fmean(y for _, y in train)
            if math.isfinite(slope) and math.isfinite(intercept):
                for test in tests:
                    baseline = _mae(test, lambda x: center)
                    challenger = _mae(test, lambda x: slope*x + intercept)
                    if baseline < 1e-7 or not math.isfinite(challenger):
                        break
                    gains.append(round(100*(baseline-challenger)/baseline,2))
                    baseline_mae.append(round(baseline,4))
                    model_mae.append(round(challenger,4))
                if len(gains) == TEST_BLOCKS:
                    success = min(gains) >= MIN_GAIN_PCT
                    status = "SHADOW_ASSOCIATION" if success else "CHALLENGE_FAILED"
                    reason = ("Improvement in two held-out chronological eras; observational association only."
                              if success else "Challenger failed to improve the baseline consistently across held-out eras.")
                else:
                    reason = "Numerically unstable baseline or model errors."
            else:
                reason = "Numerically unstable model parameters."
    result = {
        "question": recipe.question,
        "feature": recipe.feature,
        "target": recipe.target,
        "regime": recipe.regime,
        "caveat": recipe.caveat,
        "status": status,
        "training_samples": len(train),
        "test_samples_by_era": counts[TRAIN_BLOCKS:],
        "all_era_samples": counts,
        "gains_pct": gains,
        "baseline_mae_by_era": baseline_mae,
        "challenger_mae_by_era": model_mae,
        "reason": reason,
        "next_experiment": recipe.next_action,
        "priority": _status({"status": status}),
        "production_eligible": False,
        "causal_discovery": False,
        "prospective_validation": False,
    }
    return result

def architect_cycle(blocks: list[list[dict]], max_trials: int = MAX_TRIALS) -> dict:
    """Produce ranked research trials and one dynamically chosen next mission."""
    if len(blocks) != TRAIN_BLOCKS + TEST_BLOCKS:
        raise ValueError("Research must have 5 distinct historical eras.")
    if not 1 <= max_trials <= MAX_TRIALS:
        raise ValueError("Trial budget out of bounds.")
    # Preapproved deterministic catalogue. Selection by missing evidence /
    # failures is an explicit bounded autonomous policy, not unrestricted AI.
    trials = [evaluate_recipe(blocks,r) for r in RECIPES[:max_trials]]
    statuses = {
        state: sum(t["status"] == state for t in trials)
        for state in ("SHADOW_ASSOCIATION","CHALLENGE_FAILED","INSUFFICIENT_EVIDENCE")
    }
    # First choose next safety/methodology investigation based on actual data.
    conflicts = sum(classify_regime(row) == "CONFLICT" for block in blocks for row in block)
    rows_total = sum(map(len,blocks))
    conflict_pct = 100 * conflicts / rows_total if rows_total else 0
    if conflict_pct >= 5:
        mission = {
            "kind":"RESOLVE_SENSOR_CONTEXT",
            "title":"Investigate conflicting driving and charging telemetry",
            "reason":"Speed and charging-power signals disagree in multiple records; do not infer actual simultaneous charging and driving.",
            "next_experiment":"Compare state and charger telemetry in a tightly scoped, locally approved diagnostic before relabeling events.",
        }
    else:
        attempted = [t for t in trials if t["status"] == "INSUFFICIENT_EVIDENCE"]
        passed = [t for t in trials if t["status"] == "SHADOW_ASSOCIATION"]
        failed = [t for t in trials if t["status"] == "CHALLENGE_FAILED"]
        if attempted:
            t = max(attempted,key=lambda x: x["training_samples"])
            mission = {"kind":"TARGET_EVIDENCE_GAP","title":t["question"],
                       "reason":t["reason"],"next_experiment":t["next_experiment"]}
        elif passed:
            t = max(passed,key=lambda x: min(x["gains_pct"]))
            mission = {"kind":"CHALLENGE_SHADOW_MODEL","title":t["question"],
                       "reason":"Needs time-lag, independent episodes and prospective confirmation.",
                       "next_experiment":t["next_experiment"]}
        elif failed:
            t = min(failed,key=lambda x: min(x["gains_pct"]))
            mission = {"kind":"DIAGNOSE_FAILED_HYPOTHESIS","title":t["question"],
                       "reason":t["reason"],"next_experiment":t["next_experiment"]}
        else:
            mission = {"kind":"AWAIT_EVIDENCE","title":"Collect more representative evidence",
                       "reason":"No experiments eligible for further evaluation.",
                       "next_experiment":"Keep production learning unchanged."}
    return {
        "engine":"GENESIS HYPOTHESIS ARCHITECT 0.1",
        "mode":"MANUAL_LOCAL_SHADOW_ONLY",
        "input_rows":rows_total,
        "historical_eras":len(blocks),
        "trials_evaluated":len(trials),
        "status_counts":statuses,
        "conflicting_signals":conflicts,
        "conflict_pct":round(conflict_pct,2),
        "selected_next_mission":mission,
        "trials":trials,
        "automatic_model_promotion":False,
        "production_changes":False,
        "network_uploads":False,
        "note":"Preapproved offline observational recipes. Candidate improvement is not a future-time forecast or a scientific causal discovery.",
    }
