"""M9 private, opt-in research evidence ledger (no raw telemetry).

A manual command records bounded aggregate snapshots for a previously frozen
truth watch. GET endpoints read-only. This never schedules itself.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

from .prospective_truth_watch import check_watch

MAX_RECORDS=512
MAX_REPORT_SIZE=24000
MAX_READ=30
_NAME=re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
SCHEMA="""
CREATE TABLE IF NOT EXISTS watch_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 recorded_day TEXT NOT NULL,
 recorded_at INTEGER NOT NULL,
 watch_digest TEXT NOT NULL,
 evidence_digest TEXT NOT NULL,
 report_json TEXT NOT NULL,
 UNIQUE(watch_digest,evidence_digest)
);
CREATE INDEX IF NOT EXISTS idx_watch_history_day
 ON watch_history(watch_digest, recorded_at DESC);
"""

def _uri(path):
    return "file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"

def _watch_digest(watch_file: Path):
    p=Path(watch_file).expanduser().absolute()
    if not p.exists():
        return None
    if p.is_symlink() or not p.is_file() or p.stat().st_size>8192 or p.stat().st_mode & 0o077:
        raise ValueError("Private frozen watch is missing or has unsafe permissions.")
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _history_path(history_db, source_db=None,watch_file=None, *, write=False):
    p=Path(history_db).expanduser().absolute()
    source=Path(source_db).expanduser().resolve() if source_db is not None else None
    watch=Path(watch_file).expanduser().resolve() if watch_file is not None else None
    if p.is_symlink() or p.suffix != ".sqlite3" or p.resolve() in (source,watch):
        raise ValueError("Research history path must be separate private SQLite.")
    if p.exists() and (not p.is_file() or p.stat().st_mode & 0o077):
        raise ValueError("Existing history database is not private.")
    if write and (not p.parent.is_dir() or p.parent.is_symlink() or p.parent.stat().st_mode & 0o077):
        raise ValueError("Research history directory must already exist with 0700 permissions.")
    return p

def _summary(report: dict):
    if (report.get("status")!="POST_FREEZE_EVIDENCE_AVAILABLE"
        or report.get("production_changes") is not False
        or report.get("network_uploads") is not False
        or report.get("can_promote") is not False
        or report.get("automatic_execution") is not False):
        raise ValueError("Only real, nonpromoting post-freeze aggregate evidence may be recorded.")
    items=[]
    for m in report.get("models",[]):
        name=m.get("model")
        if not isinstance(name,str) or not _NAME.fullmatch(name):
            raise ValueError("Unrecognized model identifier in evidence.")
        item={k:m.get(k) for k in (
            "model","horizon_minutes","generation","samples","evidence_days",
            "model_mae_f","persistence_mae_f","model_advantage_f","assessment"
        )}
        items.append(item)
    summary={
        "status":report["status"],
        "eligible_pairs":int(report["eligible_pairs"]),
        "incomplete_pairs":int(report["incomplete_pairs"]),
        "new_generation_pairs":int(report["new_generation_pairs"]),
        "models":items
    }
    payload=json.dumps(summary,sort_keys=True,separators=(",",":"),allow_nan=False)
    if len(payload)>MAX_REPORT_SIZE or summary["eligible_pairs"]<=0 or len(items)>20:
        raise ValueError("No acceptable bounded research summary.")
    return payload

def record_history(source_db: Path, watch_file: Path, history_db: Path, *, now=None):
    """Explicit command only; bounded private append of aggregate progress."""
    clock=time.time() if now is None else float(now)
    digest=_watch_digest(watch_file)
    if digest is None:
        return {"status":"NOT_FROZEN","new_record":False}
    report=check_watch(source_db,watch_file,now=clock)
    if report["status"]!="POST_FREEZE_EVIDENCE_AVAILABLE":
        return {"status":report["status"],"new_record":False}
    payload=_summary(report)
    fingerprint=hashlib.sha256(payload.encode("utf-8")).hexdigest()
    history=_history_path(history_db,source_db,watch_file,write=True)
    # Create the database inode privately *before* sqlite opens it; never
    # expose aggregate evidence to other Unix accounts even momentarily.
    try:
        fd=os.open(history,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    day=datetime.fromtimestamp(clock,timezone.utc).strftime("%Y-%m-%d")
    with closing(sqlite3.connect(history,timeout=5)) as con:
        con.executescript(SCHEMA)
        # Serialized write to protect against simultaneous operator commands.
        con.execute("BEGIN IMMEDIATE")
        count=con.execute(
            "SELECT COUNT(*) FROM watch_history WHERE watch_digest=?",(digest,)
        ).fetchone()[0]
        present=con.execute(
            "SELECT id FROM watch_history WHERE watch_digest=? AND evidence_digest=?",
            (digest,fingerprint)).fetchone()
        if present:
            result={"status":"NO_NEW_EVIDENCE","new_record":False,
                    "existing_record_id":int(present[0]),"record_count":count}
        elif count>=MAX_RECORDS:
            result={"status":"HISTORY_CAPACITY_REVIEW_REQUIRED",
                    "new_record":False,"record_count":count}
        else:
            saved=con.execute("""
                INSERT INTO watch_history(recorded_day,recorded_at,watch_digest,
                                          evidence_digest,report_json)
                VALUES(?,?,?,?,?)
            """,(day,int(clock),digest,fingerprint,payload))
            result={"status":"RESEARCH_SNAPSHOT_RECORDED","new_record":True,
                    "record_id":int(saved.lastrowid),"record_count":count+1}
        con.commit()
    history.chmod(0o600)
    result.update({"scope":"LOCAL_GHOST_ONLY","production_changes":False,
                   "network_uploads":False,"can_promote":False,
                   "automatic_execution":False})
    return result

def read_history(watch_file: Path, history_db: Path, *, limit:int=14):
    """Read-only: does not create any files, and never reports other trials."""
    out={"status":"NOT_FROZEN","scope":"LOCAL_GHOST_ONLY",
         "snapshots":[],"total_records":0,"production_changes":False,
         "network_uploads":False,"can_promote":False,"automatic_execution":False}
    digest=_watch_digest(watch_file)
    if digest is None:return out
    out["status"]="NO_RECORDED_SNAPSHOTS"
    path=_history_path(history_db,watch_file=watch_file)
    if not path.is_file():return out
    safe_limit=max(1,min(int(limit),MAX_READ))
    try:
        with closing(sqlite3.connect(_uri(path),uri=True,timeout=5)) as con:
            con.execute("PRAGMA query_only=ON")
            out["total_records"]=int(con.execute(
                "SELECT COUNT(*) FROM watch_history WHERE watch_digest=?",
                (digest,)).fetchone()[0])
            rows=con.execute("""
                SELECT recorded_day,report_json FROM watch_history
                WHERE watch_digest=?
                ORDER BY id DESC LIMIT ?
            """,(digest,safe_limit)).fetchall()
        out["snapshots"]=[{"day_utc":day,**json.loads(payload)} for day,payload in rows]
        if rows:out["status"]="RECORDED_HISTORY_AVAILABLE"
    except (sqlite3.Error,OSError,ValueError,TypeError):
        out["status"]="HISTORY_UNAVAILABLE"
        out["snapshots"]=[]
        out["total_records"]=0
    return out
