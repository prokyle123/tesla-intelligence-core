"""M11 offline synthetic tests: one inferred event, one balanced vote."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from genesis.episode_challenge import episode_challenge
from genesis.frozen_challenger import freeze_challenger
from genesis.prospective_truth_watch import freeze_watch
from genesis.workspace import create_workspace_app

NOW=1800000000.
DAY=86400

class EpisodeChallengeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        os.chmod(self.root,0o700)
        self.db=self.root/"production.sqlite3"
        self.watch=self.root/"prospective-truth-watch.json"
        self.candidate=self.root/"prospective-challenger.json"
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript("""
            CREATE TABLE telemetry(id INTEGER PRIMARY KEY,car_id TEXT,
                battery_temp_c REAL,outside_temp_c REAL,route TEXT);
            CREATE TABLE vehicle_events(id INTEGER PRIMARY KEY,car_id TEXT,
                event_type TEXT,start_ts REAL,end_ts REAL,route TEXT);
            CREATE TABLE prediction_audit(id INTEGER PRIMARY KEY,
                predicted_at REAL,target_ts REAL,resolved_at REAL,
                status TEXT,target_field TEXT,model_name TEXT,generation INTEGER,
                horizon_minutes INTEGER,predicted_value REAL,actual_value REAL,
                source_telemetry_id INTEGER);
            """)
            con.execute("INSERT INTO telemetry VALUES(1,'PRIVATE_CAR',20,10,'SECRET_GPS')")
            con.execute("INSERT INTO telemetry VALUES(2,'PRIVATE_CAR',20,NULL,'SECRET_GPS')")
            pre=[]
            for i in range(180):
                for day in (NOW-(9+i%6)*DAY, NOW-(1+i%3)*DAY):
                    pre.append((day-4000,day-400,day,
                                "resolved","battery_temp_c","pack_temp_60m",
                                13,60,15.,16.,1))
            con.executemany("""INSERT INTO prediction_audit(
                predicted_at,target_ts,resolved_at,status,target_field,
                model_name,generation,horizon_minutes,predicted_value,
                actual_value,source_telemetry_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",pre)
            con.commit()
        freeze_watch(self.db,self.watch,now=NOW)
        freeze_challenger(self.db,self.watch,self.candidate,now=NOW)

    def future(self, events=5):
        with closing(sqlite3.connect(self.db)) as con:
            for i in range(events):
                stamp=NOW+((i%3)+1)*DAY+(i//3)*9*3600
                typ=("park","drive","charge","park","sleep")[i%5]
                con.execute("""INSERT INTO vehicle_events
                    (car_id,event_type,start_ts,end_ts,route)
                    VALUES(?,?,?,?,?)""",
                    ("PRIVATE_CAR",typ,stamp,stamp+3600,"SECRET_EVENT"))
                # One event with 100 forecasts is not allowed to overwhelm
                # four other genuinely distinct inferred events.
                for n in range(100 if i==0 else 5):
                    p=stamp+120+n*5
                    actual=20. if i==0 else 16.
                    con.execute("""INSERT INTO prediction_audit(
                        predicted_at,target_ts,resolved_at,status,target_field,
                        model_name,generation,horizon_minutes,predicted_value,
                        actual_value,source_telemetry_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (p,p+3600,p+3630,"resolved","battery_temp_c",
                         "pack_temp_60m",13,60,20.,actual,1))
            con.commit()

    def test_balances_each_event_not_forecast_count(self):
        self.future()
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        report=episode_challenge(self.db,self.watch,self.candidate,now=NOW+5*DAY)
        self.assertEqual(report["status"],"EPISODE_EVIDENCE_AVAILABLE")
        self.assertEqual(report["matched_forecasts"],120)
        self.assertEqual(report["unmatched_event_forecasts"],0)
        self.assertEqual(report["incomplete_matched_forecasts"],0)
        rows=report["model_groups"]
        self.assertEqual(sum(r["episodes"] for r in rows),5)
        self.assertEqual(sum(r["forecast_count"] for r in rows),120)
        # Group by inferred event category. "park" appears twice.
        park=next(r for r in rows if r["event_type"]=="park")
        self.assertEqual(park["episodes"],2)
        self.assertEqual(park["forecast_count"],105)
        self.assertAlmostEqual(park["challenger_mae_f"],3.6)
        self.assertAlmostEqual(park["persistence_mae_f"],3.6)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        raw=json.dumps(report)
        for secret in ("PRIVATE_CAR","SECRET_GPS","SECRET_EVENT",
                       "route","event_id","start_ts","resolved_at"):
            self.assertNotIn(secret,raw)
        for flag in ("production_changes","can_promote",
                     "automatic_execution","network_uploads"):
            self.assertFalse(report[flag])

    def test_one_event_has_insufficient_evidence_even_with_many_forecasts(self):
        self.future(events=1)
        report=episode_challenge(self.db,self.watch,self.candidate,now=NOW+5*DAY)
        self.assertEqual(report["matched_forecasts"],100)
        row=report["model_groups"][0]
        self.assertEqual(row["episodes"],1)
        self.assertEqual(row["evidence_days"],1)
        self.assertEqual(row["assessment"],"INSUFFICIENT_EPISODE_EVIDENCE")

    def test_no_new_predictions_and_missing_event_source(self):
        report=episode_challenge(self.db,self.watch,self.candidate,now=NOW+5*DAY)
        self.assertEqual(report["status"],"NO_MATCHED_EPISODE_EVIDENCE")
        self.assertEqual(report["model_groups"],[])
        with closing(sqlite3.connect(self.db)) as con:
            p=NOW+2*DAY
            con.execute("""INSERT INTO prediction_audit(
                predicted_at,target_ts,resolved_at,status,target_field,
                model_name,generation,horizon_minutes,predicted_value,
                actual_value,source_telemetry_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (p,p+3600,p+3650,"resolved","battery_temp_c",
                 "pack_temp_60m",13,60,20.,16.,1))
            con.commit()
        report=episode_challenge(self.db,self.watch,self.candidate,now=NOW+5*DAY)
        self.assertEqual(report["unmatched_event_forecasts"],1)
        self.assertEqual(report["matched_forecasts"],0)

    def test_source_event_schema_missing_returns_explicit_gap(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("DROP TABLE vehicle_events")
            con.commit()
        result=episode_challenge(self.db,self.watch,self.candidate,now=NOW+5*DAY)
        self.assertEqual(result["status"],"EVENT_SCHEMA_UNAVAILABLE")

    def test_readonly_route_not_a_new_freeze(self):
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        app.config["GENESIS_SOURCE_DB"]=str(self.db)
        with patch("genesis.api.episode_challenge",
                   return_value=episode_challenge(self.db,self.watch,self.candidate,now=NOW)):
            client=app.test_client()
            response=client.get("/api/genesis/episode-challenge")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(response.get_json()["scope"],"LOCAL_GHOST_ONLY")
            self.assertEqual(client.post("/api/genesis/episode-challenge").status_code,405)
            self.assertNotIn("SECRET_GPS",response.get_data(as_text=True))

if __name__=="__main__":
    unittest.main()
