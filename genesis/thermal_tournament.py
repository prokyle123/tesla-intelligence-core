"""GENESIS offline thermal model tournament.

Predeclared candidate predictors, episode-balanced training/validation/test,
holdout scored ONCE after selection. No generated code, new telemetry polling,
production model promotion, web access or local data storage.

The "held-out" period is historical and may have been viewed in previous
research cycles. Never interpret this as prospective or untouched discovery.
"""
from __future__ import annotations

import math
import random
import statistics
from pathlib import Path

from .episode_lab import scan_episodes

MIN_TRAIN_EPISODES = 10
MIN_VALID_EPISODES = 5
MIN_TEST_EPISODES = 5
MIN_TRAIN_PAIRS = 30
MIN_GROUP_PAIRS = 15
MIN_VALIDATION_GAIN_PCT = 10
MIN_HOLDOUT_GAIN_PCT = 10


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum,max(minimum,value))


def _train_models(train: list[list[tuple[float,float,float]]]) -> dict[str,dict]:
    pairs=[p for e in train for p in e]
    differences=[(ambient-pack,future-pack) for pack,ambient,future in pairs]
    numerator=sum(x*y for x,y in differences)
    denominator=sum(x*x for x,_ in differences)
    physical=_clamp(numerator / denominator,0.,1.) if denominator>1e-8 else 0.

    def subgroup(nonpositive):
        selected=[(x,y) for x,y in differences if (x<=0 if nonpositive else x>0)]
        denom=sum(x*x for x,_ in selected)
        if len(selected)<12 or denom<1e-8:
            return physical
        return _clamp(sum(x*y for x,y in selected)/denom,0.,1.)

    drift=_clamp(statistics.fmean(y for _,y in differences),-2.,2.)
    mx=statistics.fmean(x for x,_ in differences)
    my=statistics.fmean(y for _,y in differences)
    vx=sum((x-mx)**2 for x,_ in differences)
    slope=_clamp(sum((x-mx)*(y-my) for x,y in differences)/vx,-1.,1.) if vx>1e-8 else 0.
    intercept=_clamp(my-slope*mx,-2.,2.)
    models={
        "PERSISTENCE":{"bias":0.,"alpha":0.},
        "AMBIENT_RELAXATION":{"bias":0.,"alpha":physical},
        "DRIFT_ONLY":{"bias":drift,"alpha":0.},
        "AFFINE_THERMAL":{"bias":intercept,"alpha":slope},
        "THERMAL_ASYMMETRIC":{
            "bias":0.,"alpha_cooling":subgroup(True),"alpha_warming":subgroup(False)},
    }
    return models


def _predict(pack: float, ambient: float, model: dict) -> float:
    delta=ambient-pack
    slope=(model["alpha_cooling"] if delta<=0 else model["alpha_warming"]
           ) if "alpha_cooling" in model else model["alpha"]
    return pack + model["bias"] + slope*delta


def _episode_errors(episodes: list[list[tuple[float,float,float]]],
                    model: dict) -> list[float]:
    out=[]
    for pairs in episodes:
        if not pairs:
            raise ValueError("Nonempty complete episodes required.")
        errors=[abs(future-_predict(pack,ambient,model)) for pack,ambient,future in pairs]
        if not all(math.isfinite(err) for err in errors):
            raise ValueError("Nonfinite model prediction.")
        out.append(statistics.fmean(errors))
    return out


def _metrics(baseline_errors: list[float], other_errors: list[float]) -> dict:
    if len(baseline_errors)!=len(other_errors) or not baseline_errors:
        raise ValueError("Invalid episode errors.")
    base=statistics.fmean(baseline_errors)
    challenger=statistics.fmean(other_errors)
    pct=100*(base-challenger)/base if base>1e-6 else 0.
    return {
        "episode_balanced_baseline_mae_c":round(base,4),
        "episode_balanced_model_mae_c":round(challenger,4),
        "improvement_pct":round(pct,2),
        "episodes_better":sum(b > a for b,a in zip(baseline_errors,other_errors)),
        "episodes_evaluated":len(other_errors),
    }


def _bootstrap_improvement_ci(baseline: list[float],
                              challenger: list[float]) -> tuple[float,float]:
    """80% bootstrap uncertainty interval on absolute °C MAE benefit, by episode."""
    n=len(baseline)
    rng=random.Random(1337)
    improvements=[b-c for b,c in zip(baseline,challenger)]
    draws=[]
    for _ in range(300):
        draws.append(sum(improvements[rng.randrange(n)] for _ in range(n))/n)
    draws.sort()
    return round(draws[30],4),round(draws[269],4)


def tournament_from_episodes(episodes: list[list[tuple[float,float,float]]],
                             *, source_counts: dict|None=None) -> dict:
    if len(episodes)>3000 or any(not e or len(e)>4800 for e in episodes):
        raise ValueError("Unbounded or empty episode history.")
    n=len(episodes)
    cut1=int(n*.6)
    cut2=int(n*.8)
    train,valid,test=episodes[:cut1],episodes[cut1:cut2],episodes[cut2:]
    pairs=[sum(len(e) for e in group) for group in (train,valid,test)]
    counts=source_counts or {}
    report={
        "experiment":"GENESIS_THERMAL_MODEL_TOURNAMENT_V1",
        "status":"INSUFFICIENT_EPISODE_EVIDENCE",
        "episode_counts":{"training":len(train),"selection_validation":len(valid),
                          "historical_holdout":len(test)},
        "hourly_pairs":{"training":pairs[0],"selection_validation":pairs[1],
                        "historical_holdout":pairs[2]},
        "models_compared":[],
        "selection_method":"Validation-only lowest episode-balanced MAE with near-best preference for simpler predictors; historical holdout never used in selection.",
        "selected_model":"PERSISTENCE",
        "validation":None,
        "historical_holdout":None,
        "holdout_episode_bootstrap_80pct_interval_c":None,
        "source_rows_scanned":counts.get("scanned"),
        "missing_heater_preconditioning_rows":counts.get("unknown_heater_rows",0),
        "next_mission":"Collect sufficient separate qualifying parked episodes and investigate heater-state data availability.",
        "caveats":["PREVIOUSLY_EXPLORED_HISTORICAL_DATA_NOT_PROSPECTIVE",
                   "ONE_HOUR_FIXED_AMBIENT_PROXY",
                   "EPISODE_LABELS_FROM_INFERRED_TELEMETRY",
                   "CANDIDATE_PARAMETERS_LEARNED_ONLY_ON_TRAINING_EPISODES"],
        "production_changes":False,
        "network_uploads":False,
        "can_promote":False,
        "automatic_model_promotion":False,
    }
    if counts.get("unknown_heater_rows",0):
        report["caveats"].append("UNKNOWN_HEATER_OR_PRECONDITION_STATE_DURING_SOME_PARKED_ROWS")
    if (len(train)<MIN_TRAIN_EPISODES or len(valid)<MIN_VALID_EPISODES
        or len(test)<MIN_TEST_EPISODES or pairs[0]<MIN_TRAIN_PAIRS
        or min(pairs[1:])<MIN_GROUP_PAIRS):
        return report

    models=_train_models(train)
    baseline_valid=_episode_errors(valid,models["PERSISTENCE"])
    trial=[]
    for name,params in models.items():
        errs=_episode_errors(valid,params)
        scores=_metrics(baseline_valid,errs)
        trial.append({"model":name,
                      "validation_episode_balanced_mae_c":scores["episode_balanced_model_mae_c"],
                      "validation_improvement_pct":scores["improvement_pct"],
                      "validation_episodes_better":scores["episodes_better"],
                      "validation_episodes_evaluated":len(valid)})
    trial.sort(key=lambda x:(x["validation_episode_balanced_mae_c"],x["model"]))
    report["models_compared"]=trial
    # Predeclared near-best simplicity rule, all on validation only:
    # complexity is penalized when the difference is below a practical
    # 0.005 C or 2% of persistence error (whichever is larger). This
    # prevents a tiny numerical fitting advantage from selecting a
    # more complex, easily overfit thermal model.
    simplest={"PERSISTENCE":0,"AMBIENT_RELAXATION":1,
              "DRIFT_ONLY":1,"THERMAL_ASYMMETRIC":3,"AFFINE_THERMAL":3}
    best_mae=trial[0]["validation_episode_balanced_mae_c"]
    baseline_mae=statistics.fmean(baseline_valid)
    tolerance=max(.005,.02*baseline_mae)
    eligible=[item for item in trial
              if item["validation_episode_balanced_mae_c"]<=best_mae+tolerance]
    chosen=min(eligible,key=lambda item:(simplest[item["model"]],
                                          item["validation_episode_balanced_mae_c"],
                                          item["model"]))
    # A research challenger must still beat persistence by >=10% on
    # validation before we even test it as the preferred model.
    if (chosen["model"]!="PERSISTENCE"
            and chosen["validation_improvement_pct"]>=MIN_VALIDATION_GAIN_PCT):
        report["selected_model"]=chosen["model"]
    else:
        report["selected_model"]="PERSISTENCE"
    params=models[report["selected_model"]]
    v_errs=_episode_errors(valid,params)
    report["validation"]=_metrics(baseline_valid,v_errs)
    base_test=_episode_errors(test,models["PERSISTENCE"])
    chosen_test=_episode_errors(test,params)
    report["historical_holdout"]=_metrics(base_test,chosen_test)
    ci=_bootstrap_improvement_ci(base_test,chosen_test)
    report["holdout_episode_bootstrap_80pct_interval_c"]=list(ci)

    if report["selected_model"]=="PERSISTENCE":
        report["status"]="PERSISTENCE_RETAINED"
        report["next_mission"]="Study heating/ambient changes; no experimental model beat persistence in validation by 10%."
    elif (report["validation"]["improvement_pct"]>=MIN_VALIDATION_GAIN_PCT
          and report["historical_holdout"]["improvement_pct"]>=MIN_HOLDOUT_GAIN_PCT
          and report["historical_holdout"]["episodes_better"]>len(test)//2
          and ci[0]>0):
        report["status"]="RESEARCH_ONLY_HISTORICAL_WIN"
        report["next_mission"]=(
            "Freeze the selected model definition; score newly arriving parked episodes"
            " without changing the candidate or its hyperparameters.")
    else:
        report["status"]="HOLDOUT_CHALLENGE_FAILED"
        report["next_mission"]=(
            "Validation-selected model did not reproduce across later independent episodes;"
            " retain persistence and study state/heater uncertainty.")
    return report


def run_tournament(source_db: Path, max_scan: int=100000) -> dict:
    scanned=scan_episodes(source_db,max_rows=max_scan)
    return tournament_from_episodes(scanned["episodes"],source_counts=scanned["counts"])
