"""Read-only vehicle cards and Hive status stay separate from private fleet uploads."""
from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genesis.vehicle_snapshot import snapshot
from genesis.workspace import create_workspace_app


class LocalVehicleAndHiveUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.db=self.root/"telemetry.sqlite3"
        with sqlite3.connect(self.db) as con:
            con.execute("""CREATE TABLE telemetry (
                ts REAL, car_id TEXT, raw_json TEXT, battery_level REAL,
                battery_temp_c REAL, outside_temp_c REAL, inside_temp_c REAL,
                speed_kmh REAL, charger_power_kw REAL, pack_power_kw REAL)""")
            con.execute("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?,?,?)",
                (1000,"PRIVATE_VIN","PRIVATE_GPS_AND_ROUTE",60,21,10,19,0,0,-1))

    def test_vehicle_data_minimal_fahrenheit_and_stale(self):
        view=snapshot(self.db,now=1100)
        self.assertTrue(view["available"])
        self.assertTrue(view["fresh"])
        self.assertEqual(view["soc_percent"],60)
        self.assertAlmostEqual(view["pack_temp_f"],69.8)
        self.assertEqual(view["outside_temp_f"],50)
        self.assertEqual(view["state"],"PARKED_OR_OTHER")
        self.assertEqual(snapshot(self.db,now=2000)["state"],"STALE")
        value=json.dumps(view)
        self.assertNotIn("PRIVATE_VIN",value)
        self.assertNotIn("PRIVATE_GPS_AND_ROUTE",value)
        self.assertNotIn("raw_json",value)
        self.assertNotIn('"ts"',value)

    def test_workspace_endpoint_uses_local_readonly_source(self):
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        app.config["GENESIS_SOURCE_DB"]=str(self.db)
        client=app.test_client()
        vehicle=client.get("/api/genesis/vehicle")
        self.assertEqual(vehicle.status_code,200)
        self.assertEqual(vehicle.get_json()["soc_percent"],60)
        self.assertEqual(vehicle.headers["Cache-Control"],"no-store")
        hive=client.get("/api/genesis/hive")
        self.assertEqual(hive.status_code,200)
        self.assertEqual(hive.get_json()["mode"],"OFF")
        self.assertFalse(hive.get_json()["real_telemetry_uploads"])
        self.assertEqual(client.post("/api/genesis/hive").status_code,405)
        self.assertFalse((self.root/"hive-client").exists())

    def test_multiple_vehicle_source_fails_closed(self):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO telemetry(ts,car_id) VALUES(?,?)",(1100,"SECOND_PRIVATE_CAR"))
        out=snapshot(self.db,now=1200)
        self.assertFalse(out["available"])
        self.assertEqual(out["state"],"NO_DATA")
        self.assertNotIn("SECOND_PRIVATE_CAR",json.dumps(out))


if __name__=="__main__":
    unittest.main()
