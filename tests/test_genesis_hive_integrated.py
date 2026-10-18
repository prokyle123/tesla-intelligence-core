"""Integrated Hive tab — additive Home nav and genuine local outcome metrics."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
import re
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from ghost_tesla_ai.hive_local import bp,local_snapshot

ROOT=Path(__file__).resolve().parents[1]


class HiveLocalIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=self.root/"source.sqlite3"
        self.now=datetime(2026,10,17,20,tzinfo=timezone.utc).timestamp()
        with sqlite3.connect(self.db) as con:
            con.executescript("""
                CREATE TABLE telemetry(ts REAL, car_id TEXT, raw_json TEXT);
                CREATE TABLE vehicle_events(event_type TEXT,car_id TEXT);
                CREATE TABLE prediction_audit(
                    predicted_at REAL,resolved_at REAL,status TEXT,
                    target_field TEXT,abs_error REAL,car_id TEXT);
            """)
            con.executemany("INSERT INTO telemetry VALUES(?,?,?)",[
                (self.now-60,"PRIVATE_CAR","PRIVATE_ROUTE_LATLON"),
                (self.now-20,"PRIVATE_CAR","PRIVATE_ROUTE_LATLON")])
            con.executemany("INSERT INTO vehicle_events VALUES(?,?)",[
                ("drive","PRIVATE_CAR"),("charging","PRIVATE_CAR")])
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?)",[
                (self.now-9000,self.now-8000,"resolved","battery_temp_c",.5,"PRIVATE_CAR"),
                (self.now-7000,self.now-6000,"resolved","battery_temp_c",2.0,"PRIVATE_CAR"),
                (self.now-5000,self.now-4000,"resolved","battery_level",1.0,"PRIVATE_CAR"),
                (self.now-1000,None,"pending","battery_temp_c",None,"PRIVATE_CAR"),
            ])
        # Never depend on an optional coordinator running on the test host.
        # A live Pi may correctly report zero contributors rather than
        # "unknown"; isolate the tests to make results deterministic.
        coordinator = patch("ghost_tesla_ai.hive_local._local_coordinator",
                            return_value=None)
        coordinator.start()
        self.addCleanup(coordinator.stop)
        consent = patch("ghost_tesla_ai.hive_local._private_consent",
                        return_value={"mode":"OFF","last_success_month":None,"hourly_enabled":False})
        consent.start()
        self.addCleanup(consent.stop)

    def test_connected_coordinator_zero_is_distinct_from_disconnected(self):
        disconnected = local_snapshot(self.db, now=self.now)
        self.assertFalse(disconnected["fleet"]["available"])
        self.assertFalse(disconnected["fleet"]["coordinator_connected"])
        self.assertIsNone(disconnected["fleet"]["participating_vehicles"])

        coordinator_response = {
            "schema":"ghost-hive-public-v1",
            "reporting_nodes":0,
            "predictions_checked":0,
            "mean_error_f":None,
            "monthly":[],
        }
        with patch("ghost_tesla_ai.hive_local._local_coordinator",
                   return_value=coordinator_response):
            connected = local_snapshot(self.db, now=self.now)
        self.assertTrue(connected["fleet"]["available"])
        self.assertTrue(connected["fleet"]["coordinator_connected"])
        self.assertEqual(connected["fleet"]["participating_vehicles"],0)
        self.assertEqual(connected["fleet"]["predictions_checked"],0)
        self.assertEqual(connected["local"]["predictions_scored"],3)
        self.assertFalse(connected["hive"]["real_transfer_enabled"])

    def test_first_real_reporter_is_visible_without_public_region_disclosure(self):
        hub={
            "schema":"ghost-hive-public-v1",
            "reporting_nodes":1,
            "private_group_threshold":10,
            "monthly":[{"month":"2026-10","status":"SMALL_GROUP_PRIVATE",
                        "reporting_nodes":None,"predictions_checked":None,
                        "mean_error_f":None}],
            "regions":[],"countries":None,
            "mean_error_f":None,"predictions_checked":None,
        }
        consent={"mode":"OPTED_IN","last_success_month":"2026-10",
                 "last_success_at_utc":"2026-10-18T10:00:00Z",
                 "hourly_enabled":True,"region_code":"NORTH_AMERICA_EAST"}
        with patch("ghost_tesla_ai.hive_local._local_coordinator",return_value=hub), \
             patch("ghost_tesla_ai.hive_local._private_consent",return_value=consent):
            data=local_snapshot(self.db,now=self.now)
        self.assertEqual(data["hive"]["contribution"],"OPTED_IN")
        self.assertEqual(data["hive"]["region_code"],"NORTH_AMERICA_EAST")
        self.assertEqual(data["fleet"]["participating_vehicles"],1)
        self.assertTrue(data["fleet"]["coordinator_connected"])
        self.assertEqual(data["fleet"]["regions"],[])
        self.assertIsNone(data["fleet"]["countries"])
        self.assertIsNone(data["fleet"]["monthly"][0]["reporting_nodes"])
        self.assertIsNone(data["fleet"]["mean_error_f"])

    def test_fleet_ui_displays_verified_overall_enrollment_but_never_synthesizes_monthly_counts(self):
        html=(ROOT/"web/templates/hive.html").read_text()
        for key in ('window.hiveReporting=Number.isInteger(fleet.participating_vehicles)',
                    'overallOnly("Public monthly history appears once a reporter',
                    'Overall enrollment · not a monthly count',
                    'within the SAME UTC month',
                    'Your selected broad region (private view)',
                    'data-privacy-scope","OWNER_ONLY"',
                    'Countries and actual drive routes are not collected'):
            self.assertIn(key,html)
        self.assertIn('r.status==="SHARED_GROUP"',html)
        self.assertIn('r.reporting_nodes>=threshold',html)
        self.assertNotIn('window.hiveReporting=Number(local.predictions_scored)',html)

    def test_local_records_are_real_outcomes_not_raw_sample_predictions(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        result=local_snapshot(self.db,now=self.now)
        local=result["local"]
        self.assertEqual(local["telemetry_samples"],2)
        self.assertEqual(local["predictions_scored"],3)
        self.assertEqual(local["pending_predictions"],1)
        self.assertEqual(local["temp_predictions_scored"],2)
        self.assertEqual(local["within_2f_percent"],50)
        self.assertEqual(local["temp_mae_f"],2.25)
        self.assertEqual(local["drive_events"],1)
        self.assertEqual(result["fleet"]["regions"],[])
        self.assertIsNone(result["fleet"]["participating_vehicles"])
        self.assertFalse(result["fleet"]["available"])
        self.assertEqual(result["hive"]["contribution"],"OFF")
        self.assertFalse(result["hive"]["real_transfer_enabled"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
        serialized=json.dumps(result)
        for bad in ("PRIVATE_CAR","PRIVATE_ROUTE_LATLON","car_id","raw_json","gps","vin","longitude","latitude"):
            self.assertNotIn('"'+bad+'"' if len(bad)<9 else bad,serialized)

    def test_rolling_local_quality_is_real_scored_evidence_and_never_uploaded(self):
        from genesis.hive_member import preview
        with sqlite3.connect(self.db) as con:
            con.executemany("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?)",[
                (self.now-16*86400,self.now-15*86400,"resolved","battery_temp_c",0.5,"PRIVATE_CAR"),
                (self.now-36*86400,self.now-35*86400,"resolved","battery_temp_c",1.0,"PRIVATE_CAR"),
                (self.now+100,self.now+100,"resolved","battery_temp_c",0.1,"PRIVATE_CAR"),
            ])
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        report=local_snapshot(self.db,now=self.now)
        self.assertEqual(report["recent_quality"]["7d"]["temp_predictions_scored"],2)
        self.assertEqual(report["recent_quality"]["30d"]["temp_predictions_scored"],3)
        self.assertEqual(report["recent_quality"]["7d"]["within_2f_percent"],50)
        self.assertEqual(report["recent_quality"]["30d"]["within_2f_percent"],66.7)
        self.assertEqual(report["recent_quality"]["30d"]["temp_mae_f"],1.8)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
        self.assertNotIn("recent_quality",str(preview(self.db,month="2026-10").get("payload")))
        self.assertNotIn("PRIVATE_CAR",json.dumps(report))

    def test_no_recent_quality_returns_null_accuracy_not_fake_zero(self):
        later=local_snapshot(self.db,now=self.now+40*86400)
        self.assertEqual(later["recent_quality"]["7d"]["temp_predictions_scored"],0)
        self.assertIsNone(later["recent_quality"]["7d"]["within_2f_percent"])
        self.assertIsNone(later["recent_quality"]["7d"]["temp_mae_f"])

    def test_multicar_source_is_rejected_rather_than_combined(self):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO telemetry VALUES(?,?,?)",
                        (self.now-10,"SECOND_CAR","PRIVATE_ROUTE"))
        result=local_snapshot(self.db,now=self.now)
        self.assertEqual(result["error"],"MULTIPLE_VEHICLES_REQUIRE_PER_VEHICLE_ISOLATION")
        self.assertIsNone(result["local"]["predictions_scored"])

    def test_missing_source_is_gracefully_empty(self):
        result=local_snapshot(self.root/"missing.sqlite3",now=self.now)
        self.assertIn("error",result)
        self.assertFalse((self.root/"missing.sqlite3").exists())
        self.assertIsNone(result["local"]["predictions_scored"])

    def test_hive_route_and_read_api_are_get_only(self):
        app=Flask("hive-test",template_folder=str(ROOT/"web/templates"))
        app.register_blueprint(bp)
        app.testing=True
        with patch("ghost_tesla_ai.hive_local.config.DB_PATH",self.db):
            client=app.test_client()
            page=client.get("/hive")
            self.assertEqual(page.status_code,200)
            self.assertIn(b"GHOST <span>HIVE</span>",page.data)
            self.assertIn(b"Contributing Vehicles",page.data)
            self.assertIn(b"Contribute to GHOST Hive",page.data)
            api=client.get("/api/hive/local")
            self.assertEqual(api.status_code,200)
            self.assertEqual(api.get_json()["local"]["predictions_scored"],3)
            self.assertEqual(api.headers["Cache-Control"],"no-store")
            self.assertEqual(client.post("/api/hive/local").status_code,405)
            self.assertEqual(client.post("/hive").status_code,405)

    def test_original_home_structure_has_only_extra_link(self):
        src=(ROOT/"web/templates/index.html").read_text()
        self.assertIn('<button class="tab active" data-view="morning">Home</button>',src)
        self.assertIn('<section id="view-morning" class="view active">',src)
        self.assertEqual(src.count('href="/hive"'),1)
        self.assertNotIn('data-view="hive"',src)
        self.assertIn('href="/vehicle-sensors"',src)
        server=(ROOT/"ghost_tesla_ai/server.py").read_text()
        self.assertIn("app.register_blueprint(ghost_hive_local_bp)",server)

    def test_private_browser_startup_has_no_obsolete_dom_ids(self):
        # Regression: removing the middle opt-in banner without removing
        # its JS click-handler prevented EVERY API request from starting.
        page=(ROOT/"web/templates/hive.html").read_text()
        self.assertNotIn('id="review-sharing"',page)
        self.assertNotIn('$("review-sharing")',page)
        html_ids=set(re.findall(r'\bid="([^"]+)"',page))
        literal_lookups=set(re.findall(r'\$\("([^"]+)"\)',page))
        missing=literal_lookups-html_ids
        self.assertEqual(missing,set(),f"Broken DOM references block dashboard refresh: {missing}")
        self.assertIn('fetch("/api/hive/local"',page)
        self.assertIn('refresh();',page)

    def test_integrated_ui_has_no_second_nav_and_explicit_missing_data(self):
        src=(ROOT/"web/templates/hive.html").read_text()
        for required in ("GHOST <span>HIVE</span>","Where Our Contributors Drive",
                         "Prediction Accuracy","Battery Temperature Error",
                         "Research Activity","Top Contributing Regions",
                         "Contribute to GHOST Hive","/api/hive/local"):
            self.assertIn(required,src)
        self.assertNotIn("<nav",src)
        self.assertNotIn('href=',src)
        self.assertNotIn("427"," ".join(src.split("hero-sats")[-1:]))
        self.assertIn("Fleet network not connected",src)
        self.assertIn('id="hive-region-pins"',src)
        self.assertIn('id="region-map-note"',src)
        self.assertIn("Only opt-in broad regional summaries",src)

if __name__=="__main__":
    unittest.main()
