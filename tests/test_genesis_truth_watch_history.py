"""M9: manual, private, deduplicated aggregate watch-history contracts."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from genesis.prospective_truth_watch import freeze_watch
from genesis.truth_watch_history import read_history,record_history
NOW=1800000000.
DAY=86400

class TruthWatchHistoryTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home=Path(t.name)
        os.chmod(self.home,0o700)
        self.source=self.home/"production.sqlite3"
        self.watch=self.home/"prospective-truth-watch.json"
        self.history=self.home/"prospective-truth-history.sqlite3"
        with closing(sqlite3.connect(self.source)) as con:
            con.executescript("""
                CREATE TABLE telemetry(id INTEGER PRIMARY KEY,
                  car_id TEXT,battery_temp_c REAL,raw_json TEXT);
                CREATE TABLE prediction_audit(
                    id INTEGER PRIMARY KEY,predicted_at REAL,target_ts REAL,
                    resolved_at REAL,status TEXT,target_field TEXT,
                    model_name TEXT,generation INTEGER,horizon_minutes INTEGER,
                    predicted_value REAL,actual_value REAL,
                    source_telemetry_id INTEGER);
            """)
            con.execute("INSERT INTO telemetry VALUES(1,'PRIVATE_CAR',20,'SECRET_GPS')")
            con.execute("""INSERT INTO prediction_audit VALUES(
                 1,?,?,?,?,?,?,?,?,?,?,?)""",(
                 NOW-DAY,NOW-DAY+3600,NOW-DAY+7200,
                 "resolved","battery_temp_c","pack_temp_60m",
                 13,60,24,20,1))
            con.commit()
    def future(self, first=2, count=120):
        with closing(sqlite3.connect(self.source)) as con:
            rows=[]
            for i in range(count):
                x=first+i
                offset=(i%3)*DAY
                rows.append((x,NOW+30+offset,NOW+3600+offset,
                             NOW+7200+offset,"resolved","battery_temp_c",
                             "pack_temp_60m",13,60,24,20,1))
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rows)
            con.commit()
    def test_history_read_does_not_create_files_and_requires_freeze(self):
        d=read_history(self.watch,self.history)
        self.assertEqual(d["status"],"NOT_FROZEN")
        self.assertEqual(d["snapshots"],[])
        self.assertFalse(self.history.exists())
        self.assertEqual(record_history(self.source,self.watch,self.history,now=NOW)["status"],
                         "NOT_FROZEN")
        freeze_watch(self.source,self.watch,now=NOW)
        self.assertEqual(read_history(self.watch,self.history)["status"],
                         "NO_RECORDED_SNAPSHOTS")
        self.assertFalse(self.history.exists())
    def test_manually_record_frozen_evidence_repeated_checks_and_progress(self):
        freeze_watch(self.source,self.watch,now=NOW)
        self.future()
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        a=record_history(self.source,self.watch,self.history,now=NOW+4*DAY)
        self.assertEqual(a["status"],"RESEARCH_SNAPSHOT_RECORDED")
        self.assertTrue(a["new_record"])
        self.assertEqual(os.stat(self.history).st_mode&0o777,0o600)
        b=record_history(self.source,self.watch,self.history,now=NOW+4*DAY)
        self.assertEqual(b["status"],"NO_NEW_EVIDENCE")
        self.assertFalse(b["new_record"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)
        rows=read_history(self.watch,self.history)
        self.assertEqual(rows["status"],"RECORDED_HISTORY_AVAILABLE")
        self.assertEqual(rows["total_records"],1)
        self.assertEqual(rows["snapshots"][0]["eligible_pairs"],120)
        self.assertEqual(rows["snapshots"][0]["models"][0]["evidence_days"],3)
        raw=json.dumps(rows)
        for secret in ("PRIVATE_CAR","SECRET_GPS","car_id","raw_json",
                       "source_telemetry_id","predicted_at"):
            self.assertNotIn(secret,raw)
        self.future(first=122,count=6)
        c=record_history(self.source,self.watch,self.history,now=NOW+5*DAY)
        self.assertTrue(c["new_record"])
        self.assertEqual(read_history(self.watch,self.history)["total_records"],2)
    def test_reject_production_alias_and_world_readable_history(self):
        freeze_watch(self.source,self.watch,now=NOW)
        self.future()
        with self.assertRaises(ValueError):
            record_history(self.source,self.watch,self.source,now=NOW+4*DAY)
        self.history.write_bytes(b"")
        os.chmod(self.history,0o644)
        with self.assertRaises(ValueError):
            record_history(self.source,self.watch,self.history,now=NOW+4*DAY)
        with self.assertRaises(ValueError):
            read_history(self.watch,self.history)
if __name__=="__main__":
    unittest.main()
