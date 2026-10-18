"""GENESIS M4 production Truth Lab: independent real-outcome window regression."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from genesis.prediction_truth import prediction_truth
from genesis.workspace import create_workspace_app

NOW = 1800000000.0
DAY = 86400

class PredictionTruthTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.db = self.root / "real_source.sqlite3"
        with sqlite3.connect(self.db) as con:
            con.executescript("""
            CREATE TABLE telemetry (id INTEGER,car_id TEXT,raw_json TEXT);
            CREATE TABLE prediction_audit (
                status TEXT, resolved_at REAL, target_field TEXT,
                abs_error REAL, model_name TEXT,
                generation INTEGER, horizon_minutes INTEGER,
                predicted_at REAL, car_id TEXT);
            """)
            con.execute("INSERT INTO telemetry VALUES(1, 'PRIVATE_CAR', 'PRIVATE_ROUTE')")
            rows = []
            for n in range(120):
                rows.append(("resolved", NOW - 10 * DAY, "battery_temp_c", .8,
                             "pack_temp_60m", 5, 60, 1, "PRIVATE_CAR"))
                rows.append(("resolved", NOW - 2 * DAY, "battery_temp_c", 2.2,
                             "pack_temp_60m", 5, 60, 1, "PRIVATE_CAR"))
                rows.append(("resolved", NOW - 10 * DAY, "battery_temp_c", .8,
                             "pack_temp_180m", 8, 180, 1, "PRIVATE_CAR"))
                rows.append(("resolved", NOW - 2 * DAY, "battery_temp_c", 2.2,
                             "pack_temp_180m", 9, 180, 1, "PRIVATE_CAR"))
            rows.extend([
                ("resolved", NOW - 2 * DAY, "battery_level", 0, "soc", 1, 30, 1, "PRIVATE_CAR"),
                ("pending", NOW - 2 * DAY, "battery_temp_c", 0, "pending", 1, 60, 1, "PRIVATE_CAR"),
                ("resolved", NOW + DAY, "battery_temp_c", 0, "future", 1, 60, 1, "PRIVATE_CAR"),
                ("resolved", NOW - 20 * DAY, "battery_temp_c", 0, "old", 1, 60, 1, "PRIVATE_CAR"),
                ("resolved", NOW - 2 * DAY, "battery_temp_c", -1, "invalid_negative", 1, 60, 1, "PRIVATE_CAR"),
            ])
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?)", rows)

    def test_disjoint_windows_and_generation_guard(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        result=prediction_truth(self.db,now=NOW)
        self.assertEqual(result["status"],"OK")
        self.assertEqual(result["previous"]["samples"],240)
        self.assertEqual(result["recent"]["samples"],240)
        self.assertAlmostEqual(result["previous"]["mae_f"],1.44)
        self.assertAlmostEqual(result["recent"]["mae_f"],3.96)
        self.assertEqual(len(result["models"]),2)
        m={r["model"]:r for r in result["models"]}
        self.assertEqual(m["pack_temp_60m"]["state"],"WORSENING_TO_INVESTIGATE")
        self.assertEqual(m["pack_temp_60m"]["accuracy_change_pp"],-100)
        self.assertEqual(m["pack_temp_60m"]["mae_change_f"],2.52)
        self.assertEqual(m["pack_temp_180m"]["state"],"GENERATION_CHANGED_OR_MIXED")
        self.assertIsNone(m["pack_temp_180m"]["mae_change_f"])
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        data=json.dumps(result)
        for secret in ("PRIVATE_CAR","PRIVATE_ROUTE","car_id","raw_json","predicted_at","resolved_at"):
            self.assertNotIn(secret,data)
        self.assertFalse(result["production_changes"])
        self.assertFalse(result["network_uploads"])
        self.assertFalse(result["can_promote"])

    def test_extreme_resolved_misses_are_not_hidden(self):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?)",
                        ("resolved",NOW-2*DAY,"battery_temp_c",31.0,
                         "severe_miss",7,60,1,"PRIVATE_CAR"))
        data=prediction_truth(self.db,now=NOW)
        self.assertEqual(data["recent"]["samples"],241)
        row=next(x for x in data["models"] if x["model"]=="severe_miss")
        self.assertEqual(row["recent"]["samples"],1)
        self.assertEqual(row["recent"]["mae_f"],55.8)
        self.assertEqual(row["state"],"INSUFFICIENT_COMPARABLE_EVIDENCE")

    def test_missing_source_and_schema_are_non_mutating(self):
        missing=self.root/"missing.sqlite3"
        self.assertEqual(prediction_truth(missing,now=NOW)["status"],"SOURCE_UNAVAILABLE")
        self.assertFalse(missing.exists())
        with sqlite3.connect(self.db) as con:
            con.execute("DROP TABLE prediction_audit")
        self.assertEqual(prediction_truth(self.db,now=NOW)["status"],"SCHEMA_UNAVAILABLE")

    def test_multiple_cars_fail_closed(self):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO telemetry VALUES(2,'DIFFERENT_CAR','SECRET')")
        r=prediction_truth(self.db,now=NOW)
        self.assertEqual(r["status"],"MULTIVEHICLE_ISOLATION_REQUIRED")
        self.assertEqual(r["models"],[])

    def test_flask_route_is_get_only_and_does_not_expose_rows(self):
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        app.config["GENESIS_SOURCE_DB"]=str(self.db)
        with patch("genesis.api.prediction_truth",
                   return_value=prediction_truth(self.db,now=NOW)):
            c=app.test_client()
            response=c.get("/api/genesis/prediction-quality")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.get_json()["recent"]["samples"],240)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(c.post("/api/genesis/prediction-quality").status_code,405)
            self.assertNotIn("PRIVATE_ROUTE",response.get_data(as_text=True))

if __name__=="__main__":
    unittest.main()
