"""M7 matched model/persistence challenge on synthetic frozen outcomes."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from genesis.paired_baseline import paired_baseline
from genesis.workspace import create_workspace_app

NOW=1800000000.
DAY=86400

class PairedBaselineTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.db=self.root/"private.sqlite3"
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript("""
            CREATE TABLE telemetry (id INTEGER PRIMARY KEY,
                car_id TEXT,battery_temp_c REAL,raw_json TEXT);
            CREATE TABLE prediction_audit (status TEXT,target_field TEXT,
                resolved_at REAL,model_name TEXT,horizon_minutes INTEGER,
                generation INTEGER,predicted_value REAL,actual_value REAL,
                source_telemetry_id INTEGER);
            """)
            con.execute("INSERT INTO telemetry VALUES(1,'ONLY_CAR',20,'PRIVATE_ROUTE')")
            rows=[]
            for _ in range(120):
                rows.extend([
                    ("resolved","battery_temp_c",NOW-2*DAY,
                     "bad_forecast",60,6,12.,19.,1),
                    ("resolved","battery_temp_c",NOW-10*DAY,
                     "bad_forecast",60,6,18.,19.,1),
                    ("resolved","battery_temp_c",NOW-2*DAY,
                     "good_forecast",180,4,19.,19.,1)
                ])
            rows.extend([
                ("resolved","battery_temp_c",NOW-2*DAY,
                 "incomplete",60,4,None,19.,1),
                ("resolved","battery_level",NOW-2*DAY,
                 "battery_level",60,4,2.,3.,1),
                ("pending","battery_temp_c",NOW-2*DAY,
                 "pending",60,4,0.,19.,1),
                ("resolved","battery_temp_c",NOW+DAY,
                 "future",60,4,0.,19.,1)
            ])
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?)",rows)
            con.commit()

    def test_true_same_observation_comparison(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        d=paired_baseline(self.db,now=NOW)
        self.assertEqual(d["status"],"OK")
        self.assertEqual(d["eligible_pairs"],360)
        self.assertEqual(d["incomplete_pairs"],1)
        m={x["model"]:x for x in d["groups"]}
        self.assertEqual(m["bad_forecast"]["recent"]["samples"],120)
        self.assertEqual(m["bad_forecast"]["recent"]["model_mae_f"],12.6)
        self.assertEqual(m["bad_forecast"]["recent"]["persistence_mae_f"],1.8)
        self.assertEqual(m["bad_forecast"]["recent"]["model_advantage_f"],-10.8)
        self.assertEqual(m["bad_forecast"]["assessment"],"PERSISTENCE_BETTER_REVIEW")
        self.assertEqual(m["bad_forecast"]["previous"]["model_mae_f"],1.8)
        self.assertEqual(m["good_forecast"]["assessment"],"MODEL_BETTER_HISTORICALLY")
        self.assertEqual(m["good_forecast"]["recent"]["model_win_percent"],100)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        raw=json.dumps(d)
        for forbidden in ("ONLY_CAR","PRIVATE_ROUTE","car_id","raw_json","resolved_at"):
            self.assertNotIn(forbidden,raw)
        for flag in ("production_changes","can_promote","network_uploads","automatic_execution"):
            self.assertFalse(d[flag])

    def test_fails_closed_when_source_missing_or_multi_vehicle(self):
        missing=self.root/"missing.sqlite3"
        self.assertEqual(paired_baseline(missing,now=NOW)["status"],"SOURCE_UNAVAILABLE")
        self.assertFalse(missing.exists())
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("INSERT INTO telemetry VALUES(2,'SECOND_CAR',15,'PRIVATE')")
            con.commit()
        self.assertEqual(paired_baseline(self.db,now=NOW)["status"],
                         "MULTIVEHICLE_ISOLATION_REQUIRED")

    def test_get_only_local_api(self):
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        app.config["GENESIS_SOURCE_DB"]=str(self.db)
        with patch("genesis.api.paired_baseline",return_value=paired_baseline(self.db,now=NOW)):
            c=app.test_client()
            response=c.get("/api/genesis/paired-baseline")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(response.get_json()["eligible_pairs"],360)
            self.assertEqual(c.post("/api/genesis/paired-baseline").status_code,405)
            self.assertNotIn("PRIVATE_ROUTE",response.get_data(as_text=True))

if __name__=="__main__":
    unittest.main()
