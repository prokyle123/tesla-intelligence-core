"""Acceptance tests for real, explicit-consent monthly Hive reporting."""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from genesis.hive_monthly import validate_aggregate,AggregateError
from genesis.hive_member import configure,consent,disable,status,preview,send,ConsentError
from genesis.hive_server import create_app,enroll,revoke

MONTH="2026-10"
NOW=datetime(2026,10,18,tzinfo=timezone.utc).timestamp()

class RealHiveTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.root.chmod(0o700)
        self.source=self.root/"ghost.sqlite3"
        self.hub=self.root/"hub.sqlite3"
        self.consent_dir=self.root/"client"
        self.token_path=self.root/"token"
        with sqlite3.connect(self.source) as con:
            con.executescript("""
                CREATE TABLE telemetry(ts REAL,car_id TEXT,raw_json TEXT);
                CREATE TABLE prediction_audit(
                    status TEXT,target_field TEXT,abs_error REAL,resolved_at REAL,
                    raw_json TEXT);
            """)
            con.execute("INSERT INTO telemetry VALUES(?,?,?)",
                        (NOW,"PRIVATE_CAR_ID","PRIVATE_GPS"))
            # 30 completed real historical prediction outcomes.
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?)",[
                ("resolved","battery_temp_c",.75,NOW-i*3600,"PRIVATE_ROUTE")
                for i in range(30)])
        self.token=enroll(self.hub)
        self.token_path.write_text(self.token)
        self.token_path.chmod(0o600)
        self.client=create_app(self.hub).test_client()

    def test_protocol_requires_only_approved_monthly_fields(self):
        good={"schema":"ghost-hive-monthly-v1",
              "metric":"ghost-battery-temp-forecast-mae-v1",
              "month":MONTH,"scored_predictions":30,"total_abs_error_c":22.50,
              "source":"ghost_prediction_audit"}
        self.assertEqual(validate_aggregate(good),good)
        for leak in ("vin","gps","car_id","route","model_weights","location","exact_times"):
            with self.assertRaises(AggregateError):
                validate_aggregate({**good,leak:"PRIVATE"})
        for altered in (dict(good,scored_predictions=1),
                        dict(good,scored_predictions=True),
                        dict(good,total_abs_error_c=.12345),
                        dict(good,total_abs_error_c=float("nan")),
                        dict(good,month="2026-10-17")):
            with self.assertRaises(AggregateError):
                validate_aggregate(altered)

    def test_preview_is_readonly_and_local_consent_is_explicit(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        report=preview(self.source,month=MONTH)
        self.assertTrue(report["eligible"])
        self.assertEqual(report["scored_predictions"],30)
        self.assertEqual(report["payload"]["total_abs_error_c"],22.5)
        self.assertNotIn("PRIVATE_ROUTE",json.dumps(report))
        self.assertNotIn("PRIVATE_CAR_ID",json.dumps(report))
        self.assertEqual(before,hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertFalse(send(self.consent_dir,self.source)["sent"])
        cfg=configure(self.consent_dir,"http://127.0.0.1:8778",self.token_path)
        self.assertEqual(cfg["mode"],"OFF")
        self.assertFalse(send(self.consent_dir,self.source,confirm=True)["sent"])
        with self.assertRaises(ConsentError):
            consent(self.consent_dir)
        state=consent(self.consent_dir,acknowledged=True)
        self.assertEqual(state["mode"],"OPTED_IN")
        self.assertFalse(send(self.consent_dir,self.source)["sent"])
        self.assertEqual(send(self.consent_dir,self.source)["reason"],"MANUAL_CONFIRMATION_REQUIRED")
        self.assertEqual(disable(self.consent_dir)["mode"],"OFF")
        self.assertFalse(send(self.consent_dir,self.source,confirm=True)["sent"])
        self.assertEqual((self.consent_dir/"real-consent.json").stat().st_mode & 0o777,0o600)

    def test_hub_accepts_deduplicates_and_erases_research(self):
        payload=preview(self.source,month=MONTH)["payload"]
        h={"Authorization":"Bearer "+self.token}
        self.assertEqual(self.client.post("/v1/monthly-research",json=payload).status_code,401)
        self.assertEqual(self.client.post("/v1/monthly-research",json=payload,headers=h).status_code,202)
        self.assertEqual(self.client.post("/v1/monthly-research",json=payload,headers=h).status_code,202)
        with sqlite3.connect(self.hub) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM monthly_research").fetchone()[0],1)
        net=self.client.get("/v1/public-network").get_json()
        self.assertEqual(net["reporting_nodes"],1)
        self.assertIsNone(net["mean_error_f"])
        self.assertIsNone(net["predictions_checked"])
        self.assertEqual(net["monthly"][0]["status"],"SMALL_GROUP_PRIVATE")
        self.assertNotIn("PRIVATE_ROUTE",json.dumps(net))
        self.assertTrue(revoke(self.hub,self.token))
        with sqlite3.connect(self.hub) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM monthly_research").fetchone()[0],0)
        self.assertEqual(self.client.get("/v1/public-network").get_json()["reporting_nodes"],0)

    def test_public_quality_released_only_at_ten_distinct_enrollments(self):
        valid=preview(self.source,month=MONTH)["payload"]
        members=[self.token]+[enroll(self.hub) for _ in range(9)]
        for token in members:
            r=self.client.post("/v1/monthly-research",json=valid,
               headers={"Authorization":"Bearer "+token})
            self.assertEqual(r.status_code,202)
        published=self.client.get("/v1/public-network").get_json()
        self.assertEqual(published["reporting_nodes"],10)
        self.assertEqual(published["predictions_checked"],300)
        self.assertEqual(published["mean_error_f"],1.35)
        self.assertEqual(published["monthly"][0]["status"],"SHARED_GROUP")
        self.assertFalse(published["verified_unique_people"])
        self.assertFalse(published["model_weights_shared"])
        self.assertTrue(revoke(self.hub,members[-1]))
        restricted=self.client.get("/v1/public-network").get_json()
        self.assertEqual(restricted["reporting_nodes"],9)
        self.assertIsNone(restricted["mean_error_f"])

    def test_multivehicle_and_missing_outcomes_fail_closed(self):
        with sqlite3.connect(self.source) as con:
            con.execute("INSERT INTO telemetry VALUES(?,?,?)",(NOW,"OTHER_PRIVATE_CAR","SECRET"))
        with self.assertRaisesRegex(ConsentError,"Multiple vehicles"):
            preview(self.source,month=MONTH)
        data=dict(preview.__annotations__)
        self.assertTrue(data)

if __name__=="__main__":
    unittest.main()
