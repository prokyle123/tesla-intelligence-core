"""Episode-aware, one-hour thermal forecast challenge (experimental only).

The candidate predicts parked pack temperature one hour ahead using current
pack/ambient temperature and compares against a persistence baseline.
Episodes never cross missing/charging/driving rows, historical window boundaries
or >15min telemetry gaps. Future target observations are used ONLY for
offline training and evaluation, not as model inputs.

This estimates an observational first-order cooling coefficient, not
physical causality or prospective vehicle prediction accuracy.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
import math

from .coverage import classify_regime, _finite

HORIZON_S = 3600.0
TOLERANCE_S = 600.0
MAX_GAP_S = 900.0
ANCHOR_INTERVAL_S = 3600.0
MIN_TRAIN_EPISODES = 3
MIN_TRAIN_PAIRS = 12
MIN_TEST_EPISODES = 2
MIN_TEST_PAIRS = 5
MAX_ERAS = 5


def _episodes(rows: list[dict]) -> list[list[dict]]:
    """Split on every non-parked sample, not only on elapsed time."""
    episodes, current = [], []
    previous = None
    for r in rows:
        ts = _finite(r,"ts")
        is_parked = classify_regime(r) == "PARKED_OR_OTHER"
        heater = _finite(r,"battery_heater_on")
        precondition = _finite(r,"preconditioning")
        active_heating = (heater is not None and heater >= .5) or (
            precondition is not None and precondition >= .5)
        ok = ts is not None and is_parked and not active_heating
        if current and (not ok or previous is None
                        or not 0 < ts - previous <= MAX_GAP_S):
            episodes.append(current)
            current = []
        if ok:
            current.append(r)
            previous = ts
        else:
            previous = None
    if current:
        episodes.append(current)
    return episodes


def _episode_pairs(episode: list[dict]) -> list[tuple[float,float,float]]:
    """Nonoverlapping hourly anchors: current temp, ambient, future temp."""
    entries = [r for r in episode
               if _finite(r,"ts") is not None
               and _finite(r,"battery_temp_c") is not None
               and _finite(r,"outside_temp_c") is not None]
    if len(entries) < 2:
        return []
    times = [float(r["ts"]) for r in entries]
    pairs = []
    next_anchor = -float("inf")
    for i, r in enumerate(entries):
        t = times[i]
        if t < next_anchor:
            continue
        wanted = t + HORIZON_S
        j = bisect_left(times,wanted,lo=i+1)
        candidates = [k for k in (j-1,j) if i < k < len(times)
                      and abs(times[k]-wanted) <= TOLERANCE_S]
        if not candidates:
            continue
        selected = min(candidates,key=lambda k: abs(times[k]-wanted))
        current = float(r["battery_temp_c"])
        ambient = float(r["outside_temp_c"])
        future = float(entries[selected]["battery_temp_c"])
        pairs.append((current,ambient,future))
        next_anchor = t + ANCHOR_INTERVAL_S
    return pairs


def thermal_episode_challenge(eras: list[list[dict]]) -> dict:
    if len(eras) != MAX_ERAS or any(len(x)>2400 for x in eras):
        raise ValueError("Exactly five bounded historical eras required.")
    data = []
    for era in eras:
        episodes = _episodes(era)
        usable = [_episode_pairs(e) for e in episodes]
        usable = [e for e in usable if e]
        data.append(usable)
    training_episodes = [e for era in data[:3] for e in era]
    training = [p for e in training_episodes for p in e]
    tests = [[p for e in era for p in e] for era in data[3:]]
    counts = [sum(map(len,era)) for era in data]
    episode_counts = [len(era) for era in data]
    unknown_heater = sum(
        (_finite(r,"battery_heater_on") is None or _finite(r,"preconditioning") is None)
        for era in eras for r in era if classify_regime(r)=="PARKED_OR_OTHER")
    output = {
        "experiment":"ONE_HOUR_PARKED_PACK_THERMAL_CHALLENGE",
        "forecast_horizon_minutes":60,
        "status":"INSUFFICIENT_EPISODE_EVIDENCE",
        "eligible_episodes_by_era":episode_counts,
        "hourly_pairs_by_era":counts,
        "train_episode_count":len(training_episodes),
        "train_pair_count":len(training),
        "future_era_episode_counts":episode_counts[3:],
        "future_era_pair_counts":counts[3:],
        "heater_state_incomplete_rows":unknown_heater,
        "predicted_cooling_fraction":None,
        "baseline_mae_c_by_era":[],
        "candidate_mae_c_by_era":[],
        "gain_pct_by_era":[],
        "caveats":[
            "HISTORICAL_OUT_OF_TIME_TEST_NOT_LIVE_PROSPECTIVE_VALIDATION",
            "CURRENT_AMBIENT_ASSUMED_AS_SINGLE_HOUR_INPUT",
            "EPISODES_ARE_SENSOR_DERIVED_NOT_VERIFIED_PARKING_EVENTS",
        ],
        "automatic_model_promotion":False,
        "production_changes":False,
        "fleet_uploads":False,
    }
    if unknown_heater:
        output["caveats"].append("MISSING_BATTERY_HEATER_OR_PRECONDITION_STATE")
    if (len(training_episodes)<MIN_TRAIN_EPISODES
        or len(training)<MIN_TRAIN_PAIRS
        or any(episode_counts[i]<MIN_TEST_EPISODES or counts[i]<MIN_TEST_PAIRS for i in (3,4))):
        return output
    numerator = sum((ambient-current)*(future-current)
                    for current,ambient,future in training)
    denominator = sum((ambient-current)**2 for current,ambient,future in training)
    if denominator < 1e-8:
        output["caveats"].append("INSUFFICIENT_AMBIENT_PACK_DIFFERENCE")
        return output
    alpha = min(1.0,max(0.0,numerator/denominator))
    output["predicted_cooling_fraction"] = round(alpha,4)
    for era_pairs in tests:
        baseline = sum(abs(future-current) for current,ambient,future in era_pairs)/len(era_pairs)
        candidate = sum(abs(future-(current+alpha*(ambient-current)))
                        for current,ambient,future in era_pairs)/len(era_pairs)
        if not all(math.isfinite(x) for x in (baseline,candidate)) or baseline < 1e-4:
            output["caveats"].append("UNSTABLE_PERSISTENCE_BASELINE")
            return output
        output["baseline_mae_c_by_era"].append(round(baseline,4))
        output["candidate_mae_c_by_era"].append(round(candidate,4))
        output["gain_pct_by_era"].append(round(100*(baseline-candidate)/baseline,2))
    output["status"] = ("SHADOW_FORECAST_REPEATED_HISTORICALLY"
                         if min(output["gain_pct_by_era"]) >= 10
                         else "CHALLENGE_FAILED")
    output["next_experiment"] = (
        "Freeze the thermal hypothesis and evaluate newly observed distinct parked episodes;"
        " control active heating and weather changes." if output["status"].startswith("SHADOW")
        else "Collect genuinely independent longer parked episodes and compare"
             " temperature-lag behavior against physics and persistence."
    )
    return output
