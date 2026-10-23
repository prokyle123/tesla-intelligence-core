"""Independent GENESIS Architect ledger; no direct production DB writes.

Only hypotheses, aggregate errors, next-mission plans and counts are persisted.
Raw vehicle samples and exact event timestamps never enter this database.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

SCHEMA = """
CREATE TABLE IF NOT EXISTS architect_runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_at REAL NOT NULL,
 engine TEXT NOT NULL,
 total_trials INTEGER NOT NULL,
 shadow_trials INTEGER NOT NULL,
 failed_trials INTEGER NOT NULL,
 waiting_trials INTEGER NOT NULL,
 mission_json TEXT NOT NULL,
 conflict_pct REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS architect_trials(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id INTEGER NOT NULL REFERENCES architect_runs(id),
 feature TEXT NOT NULL,
 target TEXT NOT NULL,
 regime TEXT NOT NULL,
 status TEXT NOT NULL,
 evidence_train INTEGER NOT NULL,
 gains_json TEXT NOT NULL,
 proposal_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_architect_trial_run ON architect_trials(run_id);
"""

def _path(path: Path) -> Path:
    return Path(path).expanduser().resolve()

class ArchitectLedger:
    def __init__(self, path: Path):
        self.path = _path(path)

    def save(self, report: dict, forbidden_paths: tuple[Path,...]) -> int:
        if self.path in {_path(p) for p in forbidden_paths}:
            raise ValueError("Refusing to write to the source or other GHOST database.")
        if report.get("production_changes") is not False or report.get("network_uploads") is not False:
            raise ValueError("Only explicitly safe, local research results may be stored.")
        trials = report.get("trials",[])
        if not isinstance(trials,list) or len(trials)>12:
            raise ValueError("Invalid trial budget.")
        parent=self.path.parent
        parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        parent.chmod(0o700)
        with sqlite3.connect(self.path,timeout=5) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(SCHEMA)
            tally=report["status_counts"]
            cur=con.execute(
                "INSERT INTO architect_runs(created_at,engine,total_trials,"
                "shadow_trials,failed_trials,waiting_trials,mission_json,conflict_pct)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (time.time(),report["engine"],len(trials),
                 tally["SHADOW_ASSOCIATION"],tally["CHALLENGE_FAILED"],
                 tally["INSUFFICIENT_EVIDENCE"],
                 json.dumps(report["selected_next_mission"],sort_keys=True),
                 report["conflict_pct"]))
            run_id=cur.lastrowid
            con.executemany(
                "INSERT INTO architect_trials(run_id,feature,target,regime,status,"
                "evidence_train,gains_json,proposal_json) VALUES(?,?,?,?,?,?,?,?)",
                [(run_id,t["feature"],t["target"],t["regime"],t["status"],
                  t["training_samples"],json.dumps(t["gains_pct"]),
                  json.dumps(t,sort_keys=True)) for t in trials])
        self.path.chmod(0o600)
        return int(run_id)

    def latest(self) -> dict:
        if not self.path.is_file():
            return {"run":None,"trials":[]}
        uri="file:"+quote(str(self.path),safe="/")+"?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=2) as con:
            con.execute("PRAGMA query_only=ON")
            con.row_factory=sqlite3.Row
            row=con.execute(
                "SELECT id,created_at,engine,total_trials,shadow_trials,"
                "failed_trials,waiting_trials,mission_json,conflict_pct "
                "FROM architect_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return {"run":None,"trials":[]}
            data=dict(row)
            data["selected_next_mission"]=json.loads(data.pop("mission_json"))
            trials=[json.loads(r[0]) for r in con.execute(
                "SELECT proposal_json FROM architect_trials WHERE run_id=? "
                "ORDER BY id ASC LIMIT 12",(row["id"],))]
            return {"run":data,"trials":trials}
