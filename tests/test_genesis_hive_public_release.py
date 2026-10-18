"""Hive public site stays non-identifying; screenshot layout is no longer a mock."""
from __future__ import annotations
from datetime import datetime,timezone
import copy
import json
from pathlib import Path
import tempfile
import unittest
from genesis.hive_public import summary
from scripts.hive_public_snapshot_guard import check

ROOT=Path(__file__).resolve().parents[1]
class PublicDashboardReleaseTests(unittest.TestCase):
    def template(self):
        return json.loads((ROOT/"docs/hive/network.json").read_text())

    def test_public_placeholder_safe_and_schema_strict(self):
        d=check(self.template())
        self.assertEqual(d["reporting_nodes"],0)
        self.assertIsNone(d["predictions_checked"])
        self.assertIsNone(d["fleet_accuracy_percent"])
        self.assertFalse(d["verified_unique_people"])
        self.assertEqual(d["regions"],[])
        self.assertIsNone(d["countries"])
        for key in ("vin","gps","route","longitude","latitude","car_id","participant"):
            q=copy.deepcopy(d);q[key]="PRIVATE"
            with self.subTest(key=key),self.assertRaises(ValueError):check(q)

    def test_cohort_privacy_fails_closed(self):
        d=self.template()
        row={"month":"2026-10","label":"Oct 2026","status":"SMALL_GROUP_PRIVATE",
             "reporting_nodes":None,"predictions_checked":None,"mean_error_f":None}
        d["monthly"]=[row]
        check(d)
        for key,val in (("reporting_nodes",1),("predictions_checked",37),("mean_error_f",1.34)):
            q=copy.deepcopy(d);q["monthly"][0][key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):check(q)

    def test_valid_ten_installation_group_and_summary(self):
        d=self.template()
        d.update(source="SELF_REPORTED_ENROLLED_INSTALLATIONS",
                 network_status="COORDINATOR_REPORT",reporting_nodes=10,
                 published_at_utc="2026-10-18T08:00:00Z",
                 predictions_checked=450,mean_error_f=2.58)
        d["monthly"]=[{"month":"2026-10","label":"Oct 2026","status":"SHARED_GROUP",
             "reporting_nodes":10,"predictions_checked":450,"mean_error_f":2.58}]
        self.assertEqual(check(d)["mean_error_f"],2.58)
        for bad in (9,0,-1,True):
            q=copy.deepcopy(d);q["monthly"][0]["reporting_nodes"]=bad
            with self.assertRaises(ValueError):check(q)
        q=copy.deepcopy(d);q["monthly"][0]["mean_error_f"]=float("nan")
        with self.assertRaises(ValueError):check(q)
        q=copy.deepcopy(d);q["mean_error_f"]=0.0
        with self.assertRaises(ValueError):check(q)

    def test_private_and_public_are_same_hive_dashboard_grid(self):
        private=(ROOT/"web/templates/hive.html").read_text()
        public=(ROOT/"docs/hive/index.html").read_text()
        for s in (private,public):
            for name in ("grid-top","grid-mid","grid-bottom","globe-photo","world-map-photo",
                         "Contributing Vehicles","Prediction Accuracy",
                         "Battery Temperature Error","Top Contributing Regions",
                         "Data Privacy & Security","vehicles-chart","data-window=\"6m\""):
                self.assertIn(name,s)
            self.assertNotIn('<section class="optin">',s)
            self.assertEqual(s.count('id="consent-status"'),1)
            self.assertNotIn('id="review-sharing"',s)
            self.assertNotIn('href=',s)
            self.assertIn("No location data collected",s.replace("Contribution locations are not collected","No location data collected"))
        self.assertIn('id="hive-join"',private)
        self.assertIn("/api/hive/local",private)
        self.assertNotIn("/api/hive/control/",public)
        self.assertNotIn('<dialog ',public)
        self.assertIn('fetch("./network.json"',public)

    def test_public_workflow_contains_only_public_files(self):
        wf=(ROOT/".github/workflows/hive-public-pages.yml").read_text()
        self.assertIn("docs/hive/index.html",wf)
        self.assertIn("hive_public_snapshot_guard.py",wf)
        self.assertIn("https://*",wf)
        self.assertIn("upload-pages-artifact",wf)
        self.assertNotIn("ghost_ai.sqlite3",wf)
        self.assertNotIn("hive.sqlite3",wf)
        self.assertNotIn("genesis-product/state",wf)

if __name__=="__main__":unittest.main()
