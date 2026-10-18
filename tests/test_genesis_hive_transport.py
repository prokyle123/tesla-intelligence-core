"""Hive v0: explicit consent, bounded payload and private cohort gate."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from genesis.hive_protocol import validate,ProtocolError,MIN_COHORT
from genesis.hive_server import initialize,enroll,revoke,create_app
from genesis.hive_transfer import configure,status,disable,send,_endpoint


class HiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.chmod(0o700)
        self.db=self.root/"hive.sqlite3"
        self.state=self.root/"client"
        self.token=self.root/"token"
        initialize(self.db)

    def test_schema_fail_closed_does_not_accept_identity_location_or_raw_data(self):
        good={"schema":"genesis-hive-aggregate-v1",
              "metric":"parked_thermal_persistence_mae_c",
              "period":"2026-10","episodes":25,
              "mae_c":.75,"origin":"synthetic"}
        self.assertEqual(validate(good),good)
        for extra in ("vin","gps","raw_json","car_id","route","timestamp"):
            with self.subTest(extra=extra),self.assertRaises(ProtocolError):
                validate({**good,extra:"SECRET"})
        for bad in (dict(good,mae_c=float("nan")),
                    dict(good,mae_c=float("inf")),
                    dict(good,episodes=1),dict(good,episodes=True),
                    dict(good,period="2026-10-17"),
                    dict(good,origin="raw_telemetry")):
            with self.assertRaises(ProtocolError):
                validate(bad)
        self.assertEqual(MIN_COHORT,25)

    def test_server_enrollment_authentication_and_revoke_erases_rows(self):
        key=enroll(self.db)
        app=create_app(self.db);app.testing=True
        client=app.test_client()
        sample={"schema":"genesis-hive-aggregate-v1",
              "metric":"parked_thermal_persistence_mae_c",
              "period":"2026-10","episodes":25,
              "mae_c":.75,"origin":"synthetic"}
        self.assertEqual(client.post("/v1/contributions",json=sample).status_code,401)
        headers={"Authorization":"Bearer "+key}
        self.assertEqual(client.post("/v1/contributions",json=sample,headers=headers).status_code,202)
        self.assertEqual(client.post("/v1/contributions",json=sample,headers=headers).status_code,202)
        with __import__("sqlite3").connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM contributions").fetchone()[0],1)
        out=client.get("/v1/cohorts/2026-10",headers=headers).get_json()
        self.assertEqual(out["status"],"COHORT_WITHHELD")
        self.assertIsNone(out["aggregate"])
        self.assertTrue(revoke(self.db,key))
        self.assertFalse(revoke(self.db,key))
        with __import__("sqlite3").connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM contributions").fetchone()[0],0)
        self.assertEqual(client.post("/v1/contributions",json=sample,headers=headers).status_code,401)

    def test_distinct_participant_gate_and_aggregate_only(self):
        app=create_app(self.db);app.testing=True
        client=app.test_client()
        last_key=None
        for i in range(25):
            key=enroll(self.db);last_key=key
            sample={"schema":"genesis-hive-aggregate-v1",
                    "metric":"parked_thermal_persistence_mae_c",
                    "period":"2026-10","episodes":25,
                    "mae_c":.5+i*.02,"origin":"synthetic"}
            response=client.post("/v1/contributions",json=sample,
                                 headers={"Authorization":"Bearer "+key})
            self.assertEqual(response.status_code,202)
        output=client.get("/v1/cohorts/2026-10",
                         headers={"Authorization":"Bearer "+last_key}).get_json()
        self.assertEqual(output["status"],"RESEARCH_COHORT_AVAILABLE")
        self.assertEqual(output["participants"],25)
        self.assertEqual(output["episodes"],625)
        self.assertEqual(output["mean_mae_c"],.74)
        self.assertNotIn("participant",str(output).replace("participants",""))
        self.assertNotIn("token",json.dumps(output))
        self.assertFalse(output.get("secure_aggregation",False))
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)

    def test_transport_is_explicit_dryrun_optin_and_disable(self):
        with self.assertRaises(ValueError):
            _endpoint("http://fleet.example.com:8778")
        with self.assertRaises(ValueError):
            _endpoint("https://user:secret@fleet.example.com")
        self.assertEqual(_endpoint("http://127.0.0.1:8778"),"http://127.0.0.1:8778")
        key=enroll(self.db)
        self.token.write_text(key)
        self.token.chmod(0o600)
        self.assertEqual(status(self.state)["mode"],"OFF")
        self.assertEqual(send(self.state,transmit=True)["status"],"BLOCKED_NOT_OPTED_IN")
        cfg=configure(self.state,endpoint="http://127.0.0.1:8778",
                      token_file=self.token,test_opt_in=True)
        self.assertEqual(cfg["mode"],"SYNTHETIC_TEST")
        self.assertEqual(send(self.state)["status"],"DRY_RUN_NO_NETWORK")
        self.assertEqual(disable(self.state)["mode"],"OFF")
        self.assertEqual(send(self.state,transmit=True)["status"],"BLOCKED_NOT_OPTED_IN")
        self.assertEqual((self.state/"consent.json").stat().st_mode & 0o777,0o600)

    def test_server_rejects_giant_payload_and_invalid_media(self):
        key=enroll(self.db)
        client=create_app(self.db).test_client()
        h={"Authorization":"Bearer "+key}
        self.assertEqual(client.post("/v1/contributions",data="abc",headers=h).status_code,415)
        self.assertEqual(client.post("/v1/contributions",data="a"*2000,
                          content_type="application/json",headers=h).status_code,413)
        self.assertEqual(client.get("/v1/cohorts/2026-10").status_code,401)

if __name__=="__main__":
    unittest.main()
