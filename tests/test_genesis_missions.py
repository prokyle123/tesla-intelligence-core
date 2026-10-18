"""Vetted mission execution: conflict forensics and +60m parked thermal forecasting.

Synthetic inputs only. No vehicle commands, fleet traffic, raw route outputs
or production database modifications.
"""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genesis.conflict_mission import inspect_conflicts
from genesis.thermal_mission import (_episodes,_episode_pairs,thermal_episode_challenge)
from genesis.architect_store import ArchitectLedger
from genesis.cli import mission_followup

def conflict_eras():
    out=[]
    for era in range(5):
        rows=[]
        for i in range(150):
            speed=23.0 if i<20 or i>=65 else 0.0
            power=1.8 if 10<=i<43 else 0.0
            rows.append({"ts":1_700_000_000 + era*500000+i*60,
                         "speed_kmh":speed,"charger_power_kw":power,
                         "charge_input_kw":power*.9,
                         "raw_json":"PRIVATE_ROUTE"})
        out.append(rows)
    return out

def thermal_eras():
    out=[]
    for era in range(5):
        rows=[]
        for episode in range(5):
            outside=4+3*episode + 2*era
            initial=outside+12+episode*.8
            base=1_700_000_000+era*2000000+episode*30000
            for i in range(29):
                minutes=i*5
                pack=outside+(initial-outside)*math.exp(-.4*minutes/60)
                rows.append({"ts":base+minutes*60,
                             "speed_kmh":0.0,"charger_power_kw":0.0,
                             "outside_temp_c":float(outside),
                             "battery_temp_c":pack,
                             "battery_heater_on":0.0,
                             "preconditioning":0.0})
        out.append(rows)
    return out

class MissionTests(unittest.TestCase):
    def test_explain_conflicts_without_declaring_vehicle_charged_while_moving(self):
        report=inspect_conflicts(conflict_eras())
        self.assertEqual(report["conflicting_observations"],10*5)
        self.assertEqual(report["observations"],750)
        self.assertGreater(report["power_signal_presence_in_conflicts"]["both_power_signals"],0)
        self.assertEqual(report["selected_followup"]["status"],"REVIEW_SIGNAL_SEMANTICS")
        self.assertFalse(report["state_reclassification"])
        self.assertFalse(report["production_changes"])
        self.assertFalse(report["cloud_uploads"])
        self.assertNotIn("PRIVATE_ROUTE",json.dumps(report))
        self.assertNotIn("ts",report)

    def test_conflict_run_split_by_large_gap(self):
        blocks=conflict_eras()
        blocks[0][15]["ts"]+=3600
        # Nonmonotonic synthetic timestamp is deliberately a diagnostic
        # discontinuity, not a reason to link conflict periods together.
        report=inspect_conflicts(blocks)
        self.assertTrue(report["conflicting_run_length_buckets"]["5_to_19"]>=1)

    def test_one_hour_parked_thermal_forecast_improves_persistence(self):
        report=thermal_episode_challenge(thermal_eras())
        self.assertEqual(report["status"],"SHADOW_FORECAST_REPEATED_HISTORICALLY")
        self.assertEqual(report["forecast_horizon_minutes"],60)
        self.assertGreater(report["train_episode_count"],3)
        self.assertEqual(len(report["gain_pct_by_era"]),2)
        self.assertTrue(all(x>10 for x in report["gain_pct_by_era"]))
        self.assertTrue(0<report["predicted_cooling_fraction"]<1)
        self.assertFalse(report["automatic_model_promotion"])
        self.assertFalse(report["production_changes"])
        self.assertFalse(report["fleet_uploads"])
        self.assertEqual(report["heater_state_incomplete_rows"],0)
        self.assertNotIn("ts",report)

    def test_hot_battery_heating_excluded_and_activity_breaks_episodes(self):
        rows=thermal_eras()[0][0:29]
        rows[11]["battery_heater_on"]=1.0
        samples=_episodes(rows)
        self.assertEqual(len(samples),2)
        self.assertEqual(sum(map(len,samples)),28)
        self.assertEqual(thermal_episode_challenge([rows]*5)["status"],
                         "INSUFFICIENT_EPISODE_EVIDENCE")
        rows=thermal_eras()[0][0:29]
        rows[14]["speed_kmh"]=20.0
        self.assertEqual(len(_episodes(rows)),2)

    def test_no_misleading_conclusion_if_historical_episodes_lacking(self):
        blocks=thermal_eras()
        blocks[-1]=blocks[-1][:10]
        result=thermal_episode_challenge(blocks)
        self.assertEqual(result["status"],"INSUFFICIENT_EPISODE_EVIDENCE")
        self.assertFalse(result["production_changes"])
        with self.assertRaises(ValueError):
            thermal_episode_challenge(blocks[:4])

    def test_auto_selected_vetted_mission_reads_only_and_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            src=path/"source.sqlite3"
            arch=path/"research-architect.sqlite3"
            with sqlite3.connect(src) as con:
                con.execute("""CREATE TABLE telemetry(
                    ts REAL,car_id TEXT,raw_json TEXT,
                    speed_kmh REAL,charger_power_kw REAL,charge_input_kw REAL)""")
                con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?)",[
                    (r["ts"],"SYNTHETIC_ID","PRIVATE_ROUTE",
                     r["speed_kmh"],r["charger_power_kw"],r["charge_input_kw"])
                    for era in conflict_eras() for r in era])
            self.assertEqual(mission_followup(src,arch,100)["status"],
                             "NO_SAVED_ARCHITECT_MISSION")
            stub={
                "engine":"TEST_PLAN",
                "trials":[],
                "status_counts":{"SHADOW_ASSOCIATION":0,
                                 "CHALLENGE_FAILED":0,
                                 "INSUFFICIENT_EVIDENCE":0},
                "selected_next_mission":{
                    "kind":"RESOLVE_SENSOR_CONTEXT",
                    "title":"Investigate telemetry",
                    "reason":"Conflict threshold",
                    "next_experiment":"Read-only aggregate audit"},
                "conflict_pct":12.0,
                "production_changes":False,
                "network_uploads":False,
            }
            ArchitectLedger(arch).save(stub,(src,))
            before=(hashlib.sha256(src.read_bytes()).hexdigest(),
                    hashlib.sha256(arch.read_bytes()).hexdigest())
            report=mission_followup(src,arch,rows_per_block=100)
            self.assertEqual(report["selected_mission"],"RESOLVE_SENSOR_CONTEXT")
            self.assertEqual(report["followup"]["mission"],"RESOLVE_SENSOR_CONTEXT")
            self.assertFalse(report["production_changes"])
            self.assertFalse(report["fleet_uploads"])
            self.assertEqual(before,(hashlib.sha256(src.read_bytes()).hexdigest(),
                                    hashlib.sha256(arch.read_bytes()).hexdigest()))
            self.assertNotIn("PRIVATE_ROUTE",json.dumps(report))

if __name__=="__main__":
    unittest.main()
