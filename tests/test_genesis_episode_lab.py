"""GENESIS complete-episode forecast: offline, bounded, read-only."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genesis.episode_lab import parked_thermal_research, scan_episodes
from genesis.source import SourceUnavailable


def fixture(db, episodes=30, interrupted=False, heater=False):
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE telemetry(
            ts REAL, car_id TEXT, raw_json TEXT, speed_kmh REAL,
            charger_power_kw REAL, outside_temp_c REAL, battery_temp_c REAL,
            battery_heater_on REAL, preconditioning REAL)""")
        rows=[]
        for e in range(episodes):
            ambient=2+(e%8)*3.0
            start=1_700_000_000 + e*33000
            initial=ambient+13+(e%3)*1.5
            for i in range(29):
                elapsed=i*300
                pack=ambient+(initial-ambient)*math.exp(-.32*elapsed/3600)
                speed=25.0 if interrupted and e==3 and i==11 else 0.0
                heating=1.0 if heater and e==2 and i==10 else 0.0
                rows.append((start+elapsed,"SIMULATED_PRIVATE","DO_NOT_EXPORT_ROUTE",
                             speed,0.0,ambient,pack,heating,0.0))
        con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?,?)",rows)


class CompleteEpisodeResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"telemetry.sqlite3"
        fixture(self.db)

    def test_independent_episode_history_can_test_real_one_hour_targets(self):
        digest=hashlib.sha256(self.db.read_bytes()).hexdigest()
        r=parked_thermal_research(self.db,max_rows=1000)
        self.assertEqual(r["source_rows_inspected"],870)
        self.assertEqual(r["usable_parked_episodes"],30)
        self.assertEqual(r["episodes_train_validation_test"],[18,6,6])
        self.assertEqual(r["status"],"SHADOW_FORECAST_REPEATED_HISTORICALLY")
        self.assertEqual(len(r["gain_pct"]),2)
        self.assertTrue(all(g>=10 for g in r["gain_pct"]))
        self.assertTrue(0<r["cooling_fraction"]<1)
        self.assertFalse(r["automatic_model_promotion"])
        self.assertFalse(r["production_changes"])
        self.assertFalse(r["network_uploads"])
        self.assertFalse(r["prospective_validation"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),digest)
        s=json.dumps(r)
        self.assertNotIn("DO_NOT_EXPORT_ROUTE",s)
        self.assertNotIn("SIMULATED_PRIVATE",s)
        self.assertNotIn("car_id",s)
        self.assertNotIn('"ts"',s)

    def test_driving_and_heater_break_even_one_continuous_recorded_block(self):
        mixed=Path(self.tmp.name)/"mixed.sqlite3"
        fixture(mixed,episodes=25,interrupted=True,heater=True)
        r=parked_thermal_research(mixed,max_rows=1000)
        self.assertGreater(r["candidate_parked_episodes"],25)
        self.assertTrue(r["source_rows_inspected"]>600)
        self.assertFalse(r["production_changes"])

    def test_does_not_fabricate_episode_count_when_data_short(self):
        tiny=Path(self.tmp.name)/"tiny.sqlite3"
        fixture(tiny,episodes=3)
        report=parked_thermal_research(tiny,max_rows=1000)
        self.assertEqual(report["status"],"INSUFFICIENT_EPISODE_EVIDENCE")
        self.assertEqual(report["improvement_pct"],[])
        self.assertIsNone(report["cooling_fraction"])

    def test_fails_closed_for_multiple_vehicles(self):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO telemetry(ts,car_id) VALUES(?,?)",
                        (1_900_000_000,"OTHER_SIMULATED"))
        with self.assertRaisesRegex(SourceUnavailable,"Multiple vehicles"):
            scan_episodes(self.db,max_rows=1000)

    def test_hard_scan_limit_and_missing_source(self):
        for size in (1,999,120001,1_000_000):
            with self.subTest(rows=size),self.assertRaises(ValueError):
                scan_episodes(self.db,max_rows=size)
        p=Path(self.tmp.name)/"missing.sqlite3"
        with self.assertRaises(SourceUnavailable):
            parked_thermal_research(p,1000)
        self.assertFalse(p.exists())

    def test_source_does_not_require_or_read_identifying_columns(self):
        observed=scan_episodes(self.db,max_rows=1000)
        self.assertEqual(observed["counts"]["scanned"],870)
        self.assertGreater(len(observed["episodes"]),20)
        for episode in observed["episodes"]:
            for item in episode:
                self.assertEqual(len(item),3)
                self.assertTrue(all(isinstance(x,float) for x in item))

if __name__=="__main__":
    unittest.main()
