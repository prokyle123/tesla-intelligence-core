"""Read-only independent parked-episode research from bounded recent history.

Streams only allowlisted numeric telemetry; never loads identifiers or routes.
Groups complete inferred parked episodes across the full scan rather than
cutting each session at artificial historical-window boundaries.
"""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .coverage import classify_regime, _finite
from .source import SourceUnavailable
from .thermal_mission import _episode_pairs, MAX_GAP_S

MAX_SCAN = 120000
MAX_EPISODE = 4800
MAX_EPISODES = 3000


def scan_episodes(source_db: Path, max_rows: int = 100000) -> dict:
    if not 1000 <= max_rows <= MAX_SCAN:
        raise ValueError("Episode scan must be between 1,000 and 120,000 records.")
    path=Path(source_db).expanduser().resolve()
    if not path.is_file():
        raise SourceUnavailable("Telemetry database not available.")
    uri="file:"+quote(str(path),safe="/")+"?mode=ro"
    episodes=[]
    verified_episodes=[]
    current=[]
    unknown_in_episode=False
    overflow=False
    previous=None
    count={"scanned":0,"candidate_episodes":0,"short_episodes":0,
           "oversized_episodes":0,"unknown_heater_rows":0}
    def flush():
        nonlocal current,overflow,unknown_in_episode
        if overflow:
            count["oversized_episodes"]+=1
        elif current:
            count["candidate_episodes"]+=1
            pairs=_episode_pairs(current)
            if pairs:
                if len(episodes)>=MAX_EPISODES:
                    raise SourceUnavailable("Too many parked episodes for research limit.")
                episodes.append(pairs)
                verified_episodes.append(not unknown_in_episode)
            else:
                count["short_episodes"]+=1
        current=[]
        overflow=False
        unknown_in_episode=False
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=2.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "telemetry" not in tables:
                raise SourceUnavailable("Telemetry table missing.")
            columns={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
            required=("ts","speed_kmh","charger_power_kw","battery_temp_c","outside_temp_c")
            if not all(x in columns for x in required):
                raise SourceUnavailable("Required numeric episode signals missing.")
            if "car_id" in columns:
                distinct=con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
                if distinct>1:
                    raise SourceUnavailable("Multiple vehicles; per-vehicle isolation unavailable.")
            cols=[x for x in ("speed_kmh","charger_power_kw","charge_input_kw",
                              "battery_temp_c","outside_temp_c","battery_heater_on",
                              "preconditioning") if x in columns]
            select=",".join(['"ts"']+['"'+x+'"' for x in cols])
            sql=(f"SELECT {select} FROM (SELECT {select} FROM telemetry "
                 "ORDER BY ts DESC, rowid DESC LIMIT ?) ORDER BY ts ASC")
            for record in con.execute(sql,(max_rows,)):
                count["scanned"]+=1
                row={}
                for key,value in zip(("ts",*cols),record):
                    try:
                        f=float(value)
                        row[key]=f if math.isfinite(f) else None
                    except (TypeError,ValueError,OverflowError):
                        row[key]=None
                ts=_finite(row,"ts")
                regime=classify_regime(row)
                heater=_finite(row,"battery_heater_on")
                precond=_finite(row,"preconditioning")
                if regime=="PARKED_OR_OTHER" and (heater is None or precond is None):
                    count["unknown_heater_rows"]+=1
                heat=(heater is not None and heater>=.5) or (
                    precond is not None and precond>=.5)
                parked=ts is not None and regime=="PARKED_OR_OTHER" and not heat
                contiguous=previous is not None and ts is not None and 0<ts-previous<=MAX_GAP_S
                if current or overflow:
                    if not parked or not contiguous:
                        flush()
                if parked:
                    if heater is None or precond is None:
                        unknown_in_episode=True
                    if len(current)<MAX_EPISODE and not overflow:
                        current.append(row)
                    else:
                        current=[]
                        overflow=True
                    previous=ts
                else:
                    previous=None
            flush()
    except sqlite3.Error as exc:
        raise SourceUnavailable("Could not read thermal episodes safely.") from exc
    count["usable_episodes_with_complete_heater_state"]=sum(verified_episodes)
    count["usable_episodes_with_unknown_heater_state"]=len(verified_episodes)-sum(verified_episodes)
    return {"episodes":episodes,"counts":count,"verified_heater_episodes":verified_episodes}


def _error(pairs, alpha):
    return sum(abs(future-(pack+alpha*(ambient-pack)))
               for pack,ambient,future in pairs)/len(pairs)


def parked_thermal_research(source_db: Path, max_rows: int=100000) -> dict:
    scan=scan_episodes(source_db,max_rows)
    episodes=scan["episodes"]
    counts=scan["counts"]
    n=len(episodes)
    ntrain=int(.6*n)
    nval=int(.8*n)
    groups=(episodes[:ntrain],episodes[ntrain:nval],episodes[nval:])
    flat=[[pair for e in group for pair in e] for group in groups]
    output={
        "experiment":"FULL_HISTORY_PARKED_EPISODE_60M",
        "status":"INSUFFICIENT_EPISODE_EVIDENCE",
        "source_rows_inspected":counts["scanned"],
        "candidate_parked_episodes":counts["candidate_episodes"],
        "usable_parked_episodes":n,
        "discarded_short_episodes":counts["short_episodes"],
        "discarded_oversized_episodes":counts["oversized_episodes"],
        "missing_heater_or_preconditioning_rows":counts["unknown_heater_rows"],
        "episodes_train_validation_test":[len(g) for g in groups],
        "hourly_pairs_train_validation_test":[len(g) for g in flat],
        "cooling_fraction":None,
        "persistence_mae_c":[],
        "candidate_mae_c":[],
        "gain_pct":[],
        "caveats":[
            "HISTORICAL_EVALUATION_ONLY_NOT_FUTURE_PROSPECTIVE_CONFIRMATION",
            "INFERRED_PARKED_SESSIONS_NOT_VERIFIED_BY_TRIP_STATE",
            "ASSUMED_AMBIENT_CONSTANT_OVER_ONE_HOUR",
        ],
        "automatic_model_promotion":False,
        "production_changes":False,
        "network_uploads":False,
        "prospective_validation":False,
    }
    if counts["unknown_heater_rows"]:
        output["caveats"].append("INCOMPLETE_HEATER_PRECONDITION_TELEMETRY")
    if len(groups[0])<5 or len(groups[1])<2 or len(groups[2])<2 or len(flat[0])<12 or any(len(g)<5 for g in flat[1:]):
        output["next_experiment"]="Wait for sufficiently long independent parked sessions."
        return output
    numerator=sum((ambient-pack)*(future-pack) for pack,ambient,future in flat[0])
    denom=sum((ambient-pack)**2 for pack,ambient,future in flat[0])
    if denom<1e-8:
        output["next_experiment"]="Need training episodes with meaningful ambient-pack temperature differences."
        return output
    alpha=max(0.,min(1.,numerator/denom))
    output["cooling_fraction"]=round(alpha,5)
    for holdout in flat[1:]:
        baseline=_error(holdout,0.)
        candidate=_error(holdout,alpha)
        if baseline<1e-5 or not math.isfinite(baseline) or not math.isfinite(candidate):
            output["next_experiment"]="Persistence baseline too small or numeric results invalid."
            return output
        output["persistence_mae_c"].append(round(baseline,4))
        output["candidate_mae_c"].append(round(candidate,4))
        output["gain_pct"].append(round(100*(baseline-candidate)/baseline,2))
    output["status"]=("SHADOW_FORECAST_REPEATED_HISTORICALLY"
                      if min(output["gain_pct"])>=10 else "CHALLENGE_FAILED")
    output["next_experiment"]=(
        "Pre-register a frozen model and test newly arriving parked episodes."
        if output["status"].startswith("SHADOW") else
        "Study heater-state and changing ambient-temperature effects; keep model shadow-only.")
    return output
