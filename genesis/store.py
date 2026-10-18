"""GENESIS owns only its separate research.sqlite3, never the GHOST core DB."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from .research import Hypothesis

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_at REAL NOT NULL,
 source_rows INTEGER NOT NULL,
 evaluated INTEGER NOT NULL,
 shadows INTEGER NOT NULL,
 status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id INTEGER NOT NULL REFERENCES runs(id),
 target TEXT NOT NULL,
 feature TEXT NOT NULL,
 status TEXT NOT NULL,
 evidence_rows INTEGER NOT NULL,
 train_rows INTEGER NOT NULL,
 test_rows INTEGER NOT NULL,
 baseline_mae REAL NOT NULL,
 candidate_mae REAL NOT NULL,
 improvement_pct REAL NOT NULL,
 slope REAL NOT NULL,
 intercept REAL NOT NULL,
 reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_genesis_run ON experiments(run_id);
"""

class ResearchStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    def save(self, source_db: Path, source_rows: int, findings: list[Hypothesis]) -> int:
        if self.path == Path(source_db).expanduser().resolve():
            raise ValueError("Refusing to write to the production telemetry database.")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # SQLite may create ancillary WAL/shm files in this directory; keep it private.
        try:
            self.path.parent.chmod(0o700)
        except PermissionError:
            pass
        with sqlite3.connect(str(self.path), timeout=5.0) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(SCHEMA)
            cur = con.execute(
                "INSERT INTO runs(created_at,source_rows,evaluated,shadows,status) VALUES(?,?,?,?,?)",
                (time.time(), source_rows, len(findings),
                 sum(f.status == "SHADOW" for f in findings),
                 "RESEARCH_ONLY" if findings else "AWAITING_EVIDENCE"))
            run_id = int(cur.lastrowid)
            con.executemany(
                """INSERT INTO experiments(
                     run_id,target,feature,status,evidence_rows,train_rows,test_rows,
                     baseline_mae,candidate_mae,improvement_pct,slope,intercept,reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(run_id, f.target, f.feature, f.status, f.evidence_rows,
                  f.train_rows, f.test_rows, f.baseline_mae, f.candidate_mae,
                  f.improvement_pct, f.slope, f.intercept, f.reason) for f in findings],
            )
        self.path.chmod(0o600)
        return run_id

    def _read(self, query: str, limit: int) -> list[dict]:
        if not self.path.is_file():
            return []
        # Read-only local research database; pages are never shared with fleet service.
        from urllib.parse import quote
        uri = "file:" + quote(str(self.path), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            return [dict(x) for x in con.execute(query, (max(1, min(limit, 100)),))]

    def recent_runs(self, limit: int = 20) -> list[dict]:
        return self._read(
            "SELECT id,created_at,source_rows,evaluated,shadows,status "
            "FROM runs ORDER BY id DESC LIMIT ?", limit)

    def recent_findings(self, limit: int = 25) -> list[dict]:
        return self._read(
            "SELECT id,run_id,target,feature,status,evidence_rows,train_rows,test_rows,"
            "ROUND(baseline_mae,4) AS baseline_mae,"
            "ROUND(candidate_mae,4) AS candidate_mae,"
            "ROUND(improvement_pct,2) AS improvement_pct,reason "
            "FROM experiments ORDER BY id DESC LIMIT ?", limit)
