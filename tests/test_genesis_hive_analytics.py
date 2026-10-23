"""HIVE dashboard: eligible group-only analytics, no participant-level leakage."""
from __future__ import annotations

from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from genesis.hive_analytics import cohort_dashboard, synthetic_demo
from genesis.hive_server import create_app,enroll,revoke

NOW=datetime(2026,10,18,tzinfo=timezone.utc)

class HiveAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.db=self.root/"hive.sqlite3"
        self.app=create_app(self.db)
        self.app.testing=True
        self.client=self.app.test_client()

    def contribute(self,token,period,mae=.7,episodes=30):
        r=self.client.post("/v1/contributions",json={
            "schema":"genesis-hive-aggregate-v1",
            "metric":"parked_thermal_persistence_mae_c",
            "period":period,"episodes":episodes,"mae_c":mae,
            "origin":"synthetic",
        },headers={"Authorization":"Bearer "+token})
        self.assertEqual(r.status_code,202)

    def test_empty_cohort_withholds_all_member_counts(self):
        for _ in range(7):
            token=enroll(self.db)
            self.contribute(token,"2026-10")
        data=cohort_dashboard(self.db,now=NOW)
        self.assertEqual(data["status"],"BUILDING_PRIVATE_COHORT")
        self.assertIsNone(data["summary"]["contributors"])
        self.assertIsNone(data["summary"]["predictions_evaluated"])
        october=[row for row in data["months"] if row["period"]=="2026-10"][0]
        self.assertEqual(october["status"],"WITHHELD")
        self.assertIsNone(october["contributors"])
        self.assertIsNone(october["predictions"])
        self.assertIsNone(october["average_error_f"])
        self.assertIsNone(october["returning_contributors"])
        self.assertNotIn("PRIVATE_VIN",json.dumps(data))

    def test_distinct_eligible_cohort_and_cross_month_returning(self):
        tokens=[enroll(self.db) for _ in range(32)]
        for token in tokens[:26]:
            self.contribute(token,"2026-09",mae=.6,episodes=20)
        for token in tokens[2:32]:
            self.contribute(token,"2026-10",mae=.8,episodes=30)
        # Same node resubmits its monthly report; no double counting.
        self.contribute(tokens[2],"2026-10",mae=.8,episodes=30)
        data=cohort_dashboard(self.db,now=NOW)
        self.assertEqual(data["status"],"COHORT_AVAILABLE")
        self.assertEqual(data["summary"]["contributors"],30)
        self.assertEqual(data["summary"]["predictions_evaluated"],26*20+30*30)
        self.assertEqual(data["summary"]["average_error_f"],1.44)
        self.assertEqual(data["summary"]["returning_contributors"],24)
        self.assertEqual(data["summary"]["months_available"],2)
        self.assertTrue(data["privacy"]["individual_uploads_visible_to_server_operator"])
        self.assertFalse(data["privacy"]["anonymous_federated_learning"])
        self.assertFalse(data["privacy"]["real_car_data_enabled"])
        serialized=json.dumps(data)
        for token in tokens:self.assertNotIn(token,serialized)
        for forbidden in ("car_id","vin","gps","raw_json","participant_id","source_ip"):
            self.assertNotIn('"'+forbidden+'"',serialized)

    def test_revoke_rechecks_threshold_before_releasing_group(self):
        tokens=[enroll(self.db) for _ in range(25)]
        for token in tokens:self.contribute(token,"2026-10")
        self.assertEqual(cohort_dashboard(self.db,now=NOW)["status"],"COHORT_AVAILABLE")
        self.assertTrue(revoke(self.db,tokens[0]))
        data=cohort_dashboard(self.db,now=NOW)
        self.assertEqual(data["status"],"BUILDING_PRIVATE_COHORT")
        self.assertIsNone(data["summary"]["average_error_f"])

    def test_loopback_dashboard_and_demo_are_explicitly_labelled(self):
        r=self.client.get("/hive")
        self.assertEqual(r.status_code,200)
        self.assertIn(b"Hive Overview",r.data)
        self.assertIn(b"Research Quality",r.data)
        self.assertIn(b"SAMPLE DASHBOARD",r.data)
        self.assertEqual(r.headers["Cache-Control"],"no-store")
        self.assertIn("frame-ancestors 'none'",r.headers["Content-Security-Policy"])
        self.assertEqual(self.client.post("/hive").status_code,405)
        self.assertEqual(self.client.post("/api/hive/analytics").status_code,405)
        real=self.client.get("/api/hive/analytics")
        self.assertEqual(real.status_code,200)
        self.assertEqual(real.get_json()["status"],"BUILDING_PRIVATE_COHORT")
        demo=self.client.get("/api/hive/analytics?demo=1").get_json()
        self.assertTrue(demo["demo"])
        self.assertEqual(demo["status"],"SYNTHETIC_DEMO_ONLY")
        self.assertEqual(len(demo["months"]),6)
        self.assertIn("fictional",demo["explanation"].lower())
        self.assertNotEqual(demo["summary"]["contributors"],real.get_json()["summary"]["contributors"])
        self.assertEqual(self.client.get("/api/hive/analytics?origin=raw").status_code,400)

if __name__=="__main__":
    unittest.main()
