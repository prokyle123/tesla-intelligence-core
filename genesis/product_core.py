"""Isolated, operator-invoked GENESIS research product core.

One research cycle coordinates the Hypothesis Architect and thermal model
tournament on real local historic numeric telemetry. Research records are
aggregate-only and stay in a private standalone SQLite database.

No activation, timer, car commands, Tesla API polling, Hivemind transport,
production-model writes or automatic model promotion.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from .architect import architect_cycle
from .history_samples import historical_blocks
from .thermal_tournament import run_tournament
from .conflict_mission import inspect_conflicts


SCHEMA = """
CREATE TABLE IF NOT EXISTS product_runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_at INTEGER NOT NULL,
 state TEXT NOT NULL,
 report TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_runs_created ON product_runs(created_at);
"""
_ALLOWED_STATES = frozenset({
    "REJECTED", "PERSISTENCE_RETAINED", "MORE_EVIDENCE_NEEDED",
    "HISTORICAL_WIN_UNVERIFIED", "HISTORICAL_WIN_NOT_DEPLOYABLE"
})


def _resolved(path: Path) -> Path:
    return Path(path).expanduser().resolve()


class ProductLedger:
    """Private aggregate-only reporting, no raw data or target timestamps."""

    def __init__(self,path: Path):
        self.path=_resolved(path)

    def read_recent(self,limit: int=20) -> list[dict]:
        if not self.path.is_file():
            return []
        if self.path.is_symlink():
            raise ValueError("Symlink database rejected.")
        uri="file:"+quote(str(self.path),safe="/")+"?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=2) as con:
            con.execute("PRAGMA query_only=ON")
            result=con.execute(
                "SELECT id, created_at, state, report "
                "FROM product_runs ORDER BY id DESC LIMIT ?",
                (max(1,min(limit,50)),)).fetchall()
        out=[]
        for id_,at,state,payload in result:
            d=json.loads(payload)
            out.append({"id":id_,"created_at":at,"state":state,
                        "report":d})
        return out

    def save(self,report: dict,source_db: Path,other_protected: tuple[Path,...]=()) -> int:
        protected={_resolved(p) for p in (source_db,*other_protected)}
        if self.path in protected or self.path.is_symlink():
            raise ValueError("Refusing to write to production or existing research database.")
        state=report.get("status")
        if (state not in _ALLOWED_STATES
            or report.get("production_changes") is not False
            or report.get("network_uploads") is not False
            or report.get("can_promote") is not False):
            raise ValueError("Only nonpromoting local product summaries are accepted.")
        payload=json.dumps(report,allow_nan=False,sort_keys=True,separators=(",",":"))
        if len(payload)>32000:
            raise ValueError("Product report too large to store.")
        # Explicit schema-level report contract instead of persisting arbitrary
        # model outputs or raw source rows provided by future module authors.
        allowed={
            "status","research_mode","research_trials","architect_status_counts",
            "selected_mission","mission_followup","thermal_status","thermal_winner",
            "thermal_validation","thermal_holdout","thermal_episode_counts",
            "heater_quality","network_uploads","production_changes",
            "can_promote","caveats","next_action"
        }
        if set(report)-allowed:
            raise ValueError("Unexpected product report fields.")
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.parent.stat().st_mode & 0o077:
            raise ValueError("Product state directory must be private (0700).")
        with sqlite3.connect(self.path,timeout=5) as con:
            con.executescript(SCHEMA)
            cur=con.execute(
                "INSERT INTO product_runs(created_at,state,report) VALUES(?,?,?)",
                (int(time.time()),state,payload))
            ident=int(cur.lastrowid)
            con.commit()
        self.path.chmod(0o600)
        return ident


def _numeric_dict(value: dict|None) -> dict|None:
    if value is None:
        return None
    permitted=("episode_balanced_baseline_mae_c",
               "episode_balanced_model_mae_c",
               "improvement_pct","episodes_better","episodes_evaluated")
    return {k:value[k] for k in permitted if k in value}


def run_product_cycle(source_db: Path,product_db: Path,
                      *,max_scan: int=100000,
                      save: bool=False,
                      protected_paths: tuple[Path,...]=()) -> dict:
    """Run a bounded local research cycle; optionally record its summary."""
    source=_resolved(source_db)
    product=_resolved(product_db)
    if product==source:
        raise ValueError("Product records must not share production database.")
    windows=historical_blocks(source,blocks=5,rows_per_block=2400)
    architect=architect_cycle(windows)
    # If the architect picked sensor semantics, perform the safe static
    # diagnostic without dynamic imports or code generation.
    chosen=architect["selected_next_mission"]
    followup={"mission":chosen["kind"],"status":"PLAN_ONLY"}
    if chosen["kind"]=="RESOLVE_SENSOR_CONTEXT":
        detected=inspect_conflicts(windows)
        followup={
            "mission":chosen["kind"],
            "status":detected["selected_followup"]["status"],
            "conflicting_observations":detected["conflicting_observations"],
            "conflict_pct":detected["conflict_pct"],
        }
    thermal=run_tournament(source,max_scan=max_scan)
    winner=thermal["selected_model"]
    tstatus=thermal["status"]
    if tstatus=="RESEARCH_ONLY_HISTORICAL_WIN":
        state="HISTORICAL_WIN_NOT_DEPLOYABLE"
    elif tstatus=="RESEARCH_WIN_WITH_UNVERIFIED_HEATER_STATE":
        state="HISTORICAL_WIN_UNVERIFIED"
    elif tstatus=="INSUFFICIENT_EPISODE_EVIDENCE":
        state="MORE_EVIDENCE_NEEDED"
    elif tstatus=="PERSISTENCE_RETAINED":
        state="PERSISTENCE_RETAINED"
    else:
        state="REJECTED"
    report={
        "status":state,
        "research_mode":"LOCAL_MANUAL_SHADOW",
        "research_trials":architect["trials_evaluated"],
        "architect_status_counts":architect["status_counts"],
        "selected_mission":{
            "kind":chosen["kind"],"title":chosen["title"],
            "reason":chosen["reason"]},
        "mission_followup":followup,
        "thermal_status":tstatus,
        "thermal_winner":winner,
        "thermal_validation":_numeric_dict(thermal["validation"]),
        "thermal_holdout":_numeric_dict(thermal["historical_holdout"]),
        "thermal_episode_counts":thermal["episode_counts"],
        "heater_quality":{
            "verified_episodes":thermal["usable_episodes_complete_heater_state"],
            "unverified_episodes":thermal["usable_episodes_unknown_heater_state"]},
        "caveats":[
            "Historical source has already been explored; not prospective confirmation.",
            "Production GHOST predictions were not used as the incumbent baseline.",
            "Activity episodes and heater state can be incomplete or ambiguous.",
        ],
        "next_action":thermal["next_mission"],
        "production_changes":False,"network_uploads":False,"can_promote":False,
    }
    if save:
        report["run_id"]=ProductLedger(product).save(
            report,source,other_protected=protected_paths)
        report["saved"]=True
    else:
        report["saved"]=False
    return report
