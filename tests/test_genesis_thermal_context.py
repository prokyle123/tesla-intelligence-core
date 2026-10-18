"""Offline M6 regime and privacy regression tests."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from genesis.thermal_context import thermal_context
from genesis.workspace import create_workspace_app

NOW=1800000000.
DAY=86400

class ThermalContextTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/"vehicle.sqlite3"
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript("""
                CREATE TABLE telemetry (id INTEGER PRIMARY KEY, car_id TEXT,
                  outside_temp_c REAL, state TEXT, battery_heater_on INTEGER,
                  raw_json TEXT);
                CREATE TABLE prediction_audit (
                  status TEXT,target_field TEXT,resolved_at REAL,model_name TEXT,
                  horizon_minutes INTEGER,generation INTEGER,abs_error REAL,
                  signed_error REAL,source_telemetry_id INTEGER);
            """)
            con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?)",[
                (1,"PRIVATE_CAR",-4,"online",0,"SECRET_ROUTE"),
                (2,"PRIVATE_CAR",-4,"online",1,"SECRET_ROUTE"),
                (3,"PRIVATE_CAR",15,"driving",None,"SECRET_ROUTE"),
                (4,"PRIVATE_CAR",None,None,None,"SECRET_ROUTE")
            ])
            rows=[]
            for i in range(120):
                rows.extend([
                    ("resolved","battery_temp_c",NOW-10*DAY,"pack_temp_60m",60,17,.6,-.6,1),
                    ("resolved","battery_temp_c",NOW-2*DAY,"pack_temp_60m",60,17,4.,4.,2),
                    ("resolved","battery_temp_c",NOW-10*DAY,"pack_temp_180m",180,10,.6,.6,3),
                    ("resolved","battery_temp_c",NOW-2*DAY,"pack_temp_180m",180,11,4.,4.,3)
                ])
            rows.extend([
                ("resolved","battery_temp_c",NOW-2*DAY,"cold_pack_60m",60,5,9.,9.,4),
                ("resolved","battery_level",NOW-2*DAY,"soc_60m",60,5,1.,1.,1),
                ("pending","battery_temp_c",NOW-2*DAY,"pending",60,5,20.,20.,1),
                ("resolved","battery_temp_c",NOW+DAY,"future",60,5,20.,20.,1),
                ("resolved","battery_temp_c",NOW-25*DAY,"old",60,5,20.,20.,1),
                ("resolved","battery_temp_c",NOW-2*DAY,"invalid_negative",60,5,-1.,-1.,1)
            ])
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?)",rows)
            con.commit()

    def test_real_context_source_join_and_generation_safety(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        data=thermal_context(self.db,now=NOW)
        self.assertEqual(data["status"],"OK")
        self.assertEqual(data["matched_source_predictions"],481)
        cold=[x for x in data["dimensions"] if x["dimension"]=="ambient"
              and x["group"]=="AT_OR_BELOW_32F" and x["model"]=="pack_temp_60m"]
        self.assertEqual(len(cold),1)
        c=cold[0]
        self.assertEqual(c["recent"]["samples"],120)
        self.assertEqual(c["previous"]["samples"],120)
        self.assertEqual(c["delta_mae_f"],6.12)
        self.assertEqual(c["assessment"],"WORSENING_TO_INVESTIGATE")
        changed=[x for x in data["dimensions"] if x["model"]=="pack_temp_180m"]
        self.assertTrue(changed)
        self.assertTrue(all(x["assessment"]=="GENERATION_CHANGED_OR_MIXED"
                            for x in changed))
        self.assertTrue(data["priorities"])
        self.assertTrue(all(p["state"]=="PROPOSED_NOT_EXECUTED"
                            and p["requires_operator_review"] for p in data["priorities"]))
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        serialized=json.dumps(data)
        for secret in ("PRIVATE_CAR","SECRET_ROUTE","raw_json",
                       "source_telemetry_id","resolved_at"):
            self.assertNotIn(secret,serialized)
        for key in ("network_uploads","production_changes","can_promote","automatic_execution"):
            self.assertFalse(data[key])

    def test_missing_context_and_multiple_vehicles(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?)",
                        ("resolved","battery_temp_c",NOW-1*DAY,"cold_pack_60m",60,5,11.,11.,999))
            con.commit()
        data=thermal_context(self.db,now=NOW)
        self.assertEqual(data["unmatched_source_predictions"],1)
        self.assertTrue(any(x["group"]=="UNKNOWN" and x["dimension"]=="ambient"
                            for x in data["dimensions"]))
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("INSERT INTO telemetry VALUES(5,'OTHER',0,'driving',0,'SECRET')")
            con.commit()
        self.assertEqual(thermal_context(self.db,now=NOW)["status"],
                         "MULTIVEHICLE_ISOLATION_REQUIRED")
        missing=self.root/"missing.sqlite3"
        self.assertEqual(thermal_context(missing,now=NOW)["status"],"SOURCE_UNAVAILABLE")
        self.assertFalse(missing.exists())

    def test_optional_columns_absent_do_not_invent_context(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("ALTER TABLE telemetry RENAME TO telemetry_old")
            con.execute("CREATE TABLE telemetry(id INTEGER PRIMARY KEY,car_id TEXT)")
            con.execute("INSERT INTO telemetry SELECT id,car_id FROM telemetry_old")
            con.commit()
        data=thermal_context(self.db,now=NOW)
        self.assertEqual(data["status"],"OK")
        self.assertEqual(data["dimensions"],[])
        self.assertEqual(data["priorities"],[])

    def test_api_get_only(self):
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        app.config["GENESIS_SOURCE_DB"]=str(self.db)
        expected=thermal_context(self.db,now=NOW)
        with patch("genesis.api.thermal_context",return_value=expected):
            client=app.test_client()
            response=client.get("/api/genesis/thermal-context")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.get_json()["status"],"OK")
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(client.post("/api/genesis/thermal-context").status_code,405)
            self.assertNotIn("SECRET_ROUTE",response.get_data(as_text=True))

if __name__=="__main__":
    unittest.main()
