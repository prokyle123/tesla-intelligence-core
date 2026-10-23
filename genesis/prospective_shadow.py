"""GENESIS M3 prospective diagnostic shadow — manual, isolated, no promotion.

Freeze a research-only candidate (including FAILED historical prequalification)
against an explicit wall-clock/telemetry watermark. Later checks read only
newer telemetry, emit aggregate error metrics, and never modify GHOST.
No timer or polling installed. True arrival-time and verified charge/park
sessions are NOT available: source timestamps may be backfilled.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time
from urllib.parse import quote

from .coverage import classify_regime, _finite
from .episode_lab import scan_episodes, MAX_SCAN
from .source import SourceUnavailable
from .thermal_mission import _episode_pairs, MAX_GAP_S
from .thermal_tournament import (
    _train_models, _episode_errors, _metrics, _bootstrap_improvement_ci,
    tournament_from_episodes
)

MODEL = "AFFINE_THERMAL"  # Frozen diagnostic candidate, NOT validated.
VERSION = "GENESIS_FROZEN_SHADOW_1"
MIN_NEW_EPISODES = 10
MIN_NEW_PAIRS = 20
MAX_NEW_ROWS = 120000
MAX_PENDING_ROWS = 4800

SCHEMA = """
CREATE TABLE frozen_shadow(
 id INTEGER PRIMARY KEY CHECK(id=1),
 version TEXT NOT NULL, created_at REAL NOT NULL, cutoff_ts REAL NOT NULL,
 source_path_digest TEXT NOT NULL, model_name TEXT NOT NULL,
 parameters_json TEXT NOT NULL, parameters_sha256 TEXT NOT NULL,
 initial_historical_status TEXT NOT NULL, initial_train_episodes INTEGER NOT NULL
);
CREATE TABLE shadow_checks(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scored_at REAL NOT NULL, completed_episodes INTEGER NOT NULL,
 hourly_pairs INTEGER NOT NULL, summary_json TEXT NOT NULL
);
"""


def _source_uri(path: Path) -> str:
    return "file:" + quote(str(path.resolve()),safe="/") + "?mode=ro"


def _canonical(obj: dict) -> str:
    return json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False)


def _source_digest(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _source_highwater(source_db: Path) -> float:
    path=Path(source_db).resolve()
    if not path.is_file():
        raise SourceUnavailable("Source database not found.")
    with closing(sqlite3.connect(_source_uri(path),uri=True,timeout=2)) as con:
        con.execute("PRAGMA query_only=ON")
        try:
            value=con.execute("SELECT MAX(ts) FROM telemetry").fetchone()[0]
        except sqlite3.Error as exc:
            raise SourceUnavailable("Source timestamp high-water mark unavailable.") from exc
    if value is None or not math.isfinite(float(value)):
        raise SourceUnavailable("Source timestamp high-water mark invalid.")
    return float(value)


def _secure_state(path: Path, source_db: Path) -> Path:
    p=Path(path).expanduser().absolute()
    src=Path(source_db).expanduser().resolve()
    if p.is_symlink() or p.resolve()==src:
        raise ValueError("Refusing a symlink or a production database as shadow ledger.")
    if p.exists():
        # No state migration or overwrite performed automatically.
        if not p.is_file():
            raise ValueError("Shadow path is not a file.")
        if p.stat().st_mode & 0o077:
            raise ValueError("Existing shadow ledger permissions are not private.")
    return p


def freeze_shadow(source_db: Path, state_db: Path,
                  *, max_scan: int = 100000) -> dict:
    """Explicit one-time freeze. Existing ledgers are NEVER overwritten."""
    source=Path(source_db).expanduser().resolve()
    dest=_secure_state(state_db,source)
    if dest.exists():
        raise ValueError("Shadow experiment already frozen: refusing to alter it.")
    if not 1000<=max_scan<=MAX_SCAN:
        raise ValueError("Scan budget out of bounds.")
    # Cutoff BEFORE training starts. Historic data after this instant cannot
    # be used for fitting even if ingested during the scan.
    wall=time.time()
    high=_source_highwater(source)
    cutoff=max(wall,high)
    scan=scan_episodes(source,max_rows=max_scan)
    episodes=scan["episodes"]
    ntrain=int(len(episodes)*.6)
    training=episodes[:ntrain]
    if ntrain<10 or sum(map(len,training))<30:
        raise SourceUnavailable("Insufficient historical episodes to freeze a diagnostic model.")
    full_report=tournament_from_episodes(episodes,source_counts=scan["counts"])
    params=_train_models(training)[MODEL]
    if not all(math.isfinite(float(value)) for value in params.values()):
        raise ValueError("Non-finite fitted model parameters.")
    payload={"version":VERSION,"model":MODEL,"parameters":params,
             "training_episodes":ntrain,"initial_status":full_report["status"]}
    content=_canonical(payload)
    digest=hashlib.sha256(content.encode()).hexdigest()
    dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if dest.parent.stat().st_mode & 0o077:
        raise ValueError("Shadow directory has non-private permissions.")
    # Exclusive creation. No accidental rewriting an old experiment.
    fd=os.open(str(dest),os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
    try:
        with os.fdopen(fd,"wb",closefd=False) as file:
            file.flush()
        with closing(sqlite3.connect(dest,timeout=5)) as con:
            con.executescript(SCHEMA)
            con.execute("INSERT INTO frozen_shadow VALUES(1,?,?,?,?,?,?,?,?,?)",
                        (VERSION,wall,cutoff,_source_digest(source),MODEL,
                         _canonical(params),digest,full_report["status"],ntrain))
            con.commit()
    except Exception:
        # Avoid leaving a misleading half-frozen new experiment.
        dest.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    return {
        "status":"FROZEN_DIAGNOSTIC_ONLY",
        "model":MODEL,
        "initial_historical_status":full_report["status"],
        "historical_training_episodes":ntrain,
        "parameters_sha256":digest,
        "cutoff_rule":"New episodes must start after freeze, complete after freeze, and be recorded at later telemetry timestamps.",
        "new_completed_episodes":0,
        "can_promote":False,"production_changes":False,"network_uploads":False,
        "note":"Failed historical challenger is frozen only to measure generalization; not an accepted model.",
    }


def _load_freeze(state_db: Path,source_db: Path) -> dict:
    dest=_secure_state(state_db,source_db)
    if not dest.exists():
        raise SourceUnavailable("No shadow freeze exists. Explicitly freeze first.")
    with closing(sqlite3.connect(_source_uri(dest),uri=True,timeout=2)) as con:
        con.execute("PRAGMA query_only=ON")
        con.row_factory=sqlite3.Row
        try:
            row=con.execute("SELECT * FROM frozen_shadow WHERE id=1").fetchone()
        except sqlite3.Error as exc:
            raise SourceUnavailable("Frozen experiment ledger unreadable.") from exc
    if row is None:
        raise SourceUnavailable("Frozen experiment state missing.")
    d=dict(row)
    if d["source_path_digest"]!=_source_digest(Path(source_db)):
        raise ValueError("Frozen experiment belongs to another source database.")
    model_params=json.loads(d["parameters_json"])
    payload={"version":d["version"],"model":d["model_name"],
             "parameters":model_params,"training_episodes":d["initial_train_episodes"],
             "initial_status":d["initial_historical_status"]}
    if hashlib.sha256(_canonical(payload).encode()).hexdigest()!=d["parameters_sha256"]:
        raise ValueError("Frozen model integrity verification failed.")
    if d["version"]!=VERSION or d["model_name"]!=MODEL:
        raise ValueError("Unsupported frozen model version or name.")
    if set(model_params)!={"bias","alpha"}:
        raise ValueError("Frozen model parameters invalid.")
    if not all(math.isfinite(float(x)) for x in model_params.values()):
        raise ValueError("Nonfinite frozen parameters.")
    d["parameters"]=model_params
    return d


def _new_completed_episodes(source_db: Path,cutoff: float,
                            *, max_scan: int=100000, now: float|None=None) -> dict:
    """Strict >freeze UTC watermark; ignore opening partial and current tail.

    Read at most max_scan+1 rows to detect overflow and fail closed. Repeated
    calls recompute cumulative episode metrics; history is not re-trained.
    """
    if not 1000<=max_scan<=MAX_NEW_ROWS:
        raise ValueError("New-row scan budget invalid.")
    wall=time.time() if now is None else float(now)
    episodes=[];complete_verified=[]
    current=[];previous=None;eligible_start=False;unknown=False;overflow=False
    stats={"source_rows_since_freeze":0,"discarded_partial_start":0,
           "excluded_incomplete_tail":0,"episodes_without_hourly_pairs":0,
           "episodes_with_unknown_heater_state":0,"incomplete_heater_rows":0}
    def flush():
        nonlocal current,unknown,overflow
        if current and not overflow:
            pairs=_episode_pairs(current)
            if pairs:
                episodes.append(pairs)
                complete_verified.append(not unknown)
            else:
                stats["episodes_without_hourly_pairs"]+=1
        current=[];unknown=False;overflow=False
    path=Path(source_db).expanduser().resolve()
    if not path.is_file():
        raise SourceUnavailable("Source database missing.")
    with closing(sqlite3.connect(_source_uri(path),uri=True,timeout=2)) as con:
        con.execute("PRAGMA query_only=ON")
        cols={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
        required={"ts","speed_kmh","charger_power_kw","outside_temp_c","battery_temp_c"}
        if not required.issubset(cols):
            raise SourceUnavailable("Required prospective source signals missing.")
        if "car_id" in cols:
            cars=con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
            if cars>1:
                raise SourceUnavailable("Multiple vehicles: no isolated shadow scoring.")
        metrics=[x for x in ("speed_kmh","charger_power_kw","charge_input_kw",
                             "outside_temp_c","battery_temp_c",
                             "battery_heater_on","preconditioning") if x in cols]
        selected=",".join(['"ts"']+['"'+x+'"' for x in metrics])
        sql=(f"SELECT {selected} FROM telemetry WHERE ts>? AND ts<=? "
             "ORDER BY ts ASC,rowid ASC LIMIT ?")
        for record in con.execute(sql,(cutoff,wall,max_scan+1)):
            stats["source_rows_since_freeze"]+=1
            if stats["source_rows_since_freeze"]>max_scan:
                raise SourceUnavailable("New-data scan capacity reached: no partial prospective score permitted.")
            row={}
            for name,val in zip(("ts",*metrics),record):
                try:
                    x=float(val)
                    row[name]=x if math.isfinite(x) else None
                except (ValueError,TypeError,OverflowError):
                    row[name]=None
            ts=_finite(row,"ts")
            regime=classify_regime(row)
            heater=_finite(row,"battery_heater_on")
            precond=_finite(row,"preconditioning")
            active=(heater is not None and heater>=.5) or (
                    precond is not None and precond>=.5)
            parked=ts is not None and regime=="PARKED_OR_OTHER" and not active
            gap=previous is not None and ts is not None and not 0<ts-previous<=MAX_GAP_S
            if gap:
                if current or overflow:
                    # Gap alone is NOT proof that parking ended. Drop the
                    # interrupted session instead of scoring partial data.
                    stats["discarded_gap_episodes"]=stats.get("discarded_gap_episodes",0)+1
                    current=[];unknown=False;overflow=False
                eligible_start=True
            if not parked:
                if current or overflow: flush()
                eligible_start=True
                previous=None
                continue
            if not eligible_start:
                stats["discarded_partial_start"]+=1
                previous=ts
                continue
            if heater is None or precond is None:
                stats["incomplete_heater_rows"]+=1
                unknown=True
            if len(current)>=MAX_PENDING_ROWS:
                # do NOT create artificial independent episodes by splitting
                overflow=True;current=[]
            if not overflow:
                current.append(row)
            previous=ts
    # A currently parked episode might grow further: exclude until it
    # has an observed exit (driving, charging, activity gap).
    if current or overflow:
        stats["excluded_incomplete_tail"]=len(current)
    stats["episodes_with_unknown_heater_state"]=sum(not v for v in complete_verified)
    return {"episodes":episodes,"verified":complete_verified,"counts":stats}


def score_shadow(source_db: Path,state_db: Path,
                 *,max_scan: int=100000,now: float|None=None) -> dict:
    """Manual score: metadata only; store a summary only when count increases."""
    frozen=_load_freeze(state_db,source_db)
    post=_new_completed_episodes(source_db,float(frozen["cutoff_ts"]),
                                  max_scan=max_scan,now=now)
    episodes=post["episodes"]
    verified=post["verified"]
    n=len(episodes)
    pairs=sum(map(len,episodes))
    outcome={
        "status":"AWAITING_COMPLETE_POST_FREEZE_EPISODES",
        "model":MODEL,"parameters_sha256":frozen["parameters_sha256"],
        "initial_historical_status":frozen["initial_historical_status"],
        "completed_post_freeze_episodes":n,"post_freeze_hourly_pairs":pairs,
        "heater_verified_episodes":sum(verified),
        "heater_unverified_episodes":n-sum(verified),
        "source_records_since_freeze":post["counts"]["source_rows_since_freeze"],
        "excluded_incomplete_tail_rows":post["counts"]["excluded_incomplete_tail"],
        "persistence_episode_balanced_mae_c":None,
        "candidate_episode_balanced_mae_c":None,
        "improvement_pct":None,
        "better_episodes":None,
        "bootstrap_80pct_mae_benefit_c":None,
        "production_changes":False,"network_uploads":False,
        "can_promote":False,
        "caveats":[
            "SOURCE_TIMESTAMPS_ONLY_NOT_VERIFIED_ARRIVAL_TIMES",
            "ACTIVITY_FROM_NUMERIC_SIGNAL_INFERENCE",
            "MODEL_FAILED_HISTORICAL_PREQUALIFICATION",
            "NO_INCUMBENT_GHOST_MODEL_COMPARISON",
        ]
    }
    if n>=MIN_NEW_EPISODES and pairs>=MIN_NEW_PAIRS:
        baseline=_episode_errors(episodes,{"bias":0.,"alpha":0.})
        challenger=_episode_errors(episodes,frozen["parameters"])
        metrics=_metrics(baseline,challenger)
        ci=_bootstrap_improvement_ci(baseline,challenger)
        outcome.update({
            "persistence_episode_balanced_mae_c":metrics["episode_balanced_baseline_mae_c"],
            "candidate_episode_balanced_mae_c":metrics["episode_balanced_model_mae_c"],
            "improvement_pct":metrics["improvement_pct"],
            "better_episodes":metrics["episodes_better"],
            "bootstrap_80pct_mae_benefit_c":list(ci),
        })
        if n!=sum(verified):
            outcome["status"]="SHADOW_SCORE_HEATER_UNVERIFIED"
            outcome["caveats"].append("INCOMPLETE_HEATER_STATE_IN_NEW_EPISODES")
        elif (metrics["improvement_pct"]>=10
              and metrics["episodes_better"]>n//2 and ci[0]>0):
            outcome["status"]="SHADOW_POSITIVE_NEW_DATA_SIGNAL"
        else:
            outcome["status"]="SHADOW_MODEL_NOT_SUPPORTED_ON_NEW_DATA"
    elif n!=sum(verified):
        outcome["caveats"].append("INCOMPLETE_HEATER_STATE_IN_NEW_EPISODES")
    # Count-only summary ledger. Does not persist individual sensor readings,
    # episode IDs, routes, exact trip times, future target values or locations.
    dest=_secure_state(state_db,source_db)
    with closing(sqlite3.connect(dest,timeout=5)) as con:
        prev=con.execute(
            "SELECT completed_episodes FROM shadow_checks ORDER BY id DESC LIMIT 1").fetchone()
        if prev is None or n>prev[0]:
            con.execute(
                "INSERT INTO shadow_checks(scored_at,completed_episodes,hourly_pairs,summary_json) "
                "VALUES(?,?,?,?)",(time.time(),n,pairs,_canonical(outcome)))
            con.commit()
            outcome["new_summary_recorded"]=True
        else:
            outcome["new_summary_recorded"]=False
    return outcome


def shadow_status(state_db: Path,source_db: Path) -> dict:
    frozen=_load_freeze(state_db,source_db)
    with closing(sqlite3.connect(_source_uri(Path(state_db)),uri=True,timeout=2)) as con:
        con.execute("PRAGMA query_only=ON")
        latest=con.execute(
            "SELECT summary_json FROM shadow_checks ORDER BY id DESC LIMIT 1").fetchone()
        total=con.execute("SELECT COUNT(*) FROM shadow_checks").fetchone()[0]
    return {
        "status":"FROZEN_SHADOW_DIAGNOSTIC_ONLY",
        "model":MODEL,"parameters_sha256":frozen["parameters_sha256"],
        "initial_historical_status":frozen["initial_historical_status"],
        "summary_checks_recorded":total,
        "latest_summary":json.loads(latest[0]) if latest else None,
        "production_changes":False,"network_uploads":False,
        "can_promote":False,
    }
