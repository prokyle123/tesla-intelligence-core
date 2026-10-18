"""GENESIS Hypothesis Architect: safe proposal selection and local shadow tests."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genesis.architect import RECIPES, architect_cycle, evaluate_recipe
from genesis.architect_store import ArchitectLedger
from genesis.cli import architect_once
from genesis.history_samples import historical_blocks
from genesis.source import SourceUnavailable


def synthetic_blocks():
    eras = []
    for era in range(5):
        rows = []
        for i in range(390):
            # Stable physically plausible synthetic relationships across eras.
            ts = 1_700_000_000 + era*2000000 + i*180
            regime = i % 3
            speed = (10+i%25) if regime == 0 else 0.0
            charger = (1.5+(i%18)*.2) if regime == 1 else 0.0
            outside = 10 + 8*math.sin(i*.113+era*.2)
            pack_temp = 20 + outside*.9 + .15*math.sin(i*1.9)
            amps = speed*.4 if regime == 0 else charger*4 if regime == 1 else 0.1
            rows.append({
                "ts":float(ts),"speed_kmh":speed,"charger_power_kw":charger,
                "outside_temp_c":outside,"battery_temp_c":pack_temp,
                "battery_level":68 - era*2 + math.sin(i*.087),
                "pack_current_abs_a":amps,
                "pack_power_kw":amps*.39,
                "module_temp_spread_c":.4 + pack_temp*.04,
            })
        eras.append(rows)
    return eras


def write_fixture(path: Path, blocks):
    with sqlite3.connect(path) as c:
        c.execute("""CREATE TABLE telemetry (
            ts REAL,car_id TEXT,raw_json TEXT,speed_kmh REAL,
            charger_power_kw REAL,outside_temp_c REAL,battery_temp_c REAL,
            battery_level REAL,pack_current_abs_a REAL,pack_power_kw REAL,
            module_temp_spread_c REAL)""")
        c.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?,?,?,?)",[
            (r["ts"],"SIMULATED_CAR","PRIVATE_LOCATION",
             r["speed_kmh"],r["charger_power_kw"],r["outside_temp_c"],
             r["battery_temp_c"],r["battery_level"],r["pack_current_abs_a"],
             r["pack_power_kw"],r["module_temp_spread_c"])
            for block in blocks for r in block])

class ArchitectTests(unittest.TestCase):
    def test_creates_actual_multiera_shadow_trials(self):
        report=architect_cycle(synthetic_blocks())
        self.assertGreaterEqual(report["trials_evaluated"],10)
        self.assertTrue(any(t["status"]=="SHADOW_ASSOCIATION" for t in report["trials"]))
        temp=next(t for t in report["trials"] if t["feature"]=="outside_temp_c"
                  and t["regime"]=="PARKED_OR_OTHER" and t["target"]=="battery_temp_c")
        self.assertEqual(temp["status"],"SHADOW_ASSOCIATION")
        self.assertEqual(len(temp["gains_pct"]),2)
        self.assertTrue(all(g>10 for g in temp["gains_pct"]))
        self.assertFalse(report["automatic_model_promotion"])
        self.assertFalse(report["network_uploads"])
        self.assertFalse(report["production_changes"])

    def test_conflict_priority_selected_from_evidence(self):
        eras=synthetic_blocks()
        for b in eras:
            for row in b[:50]:
                row["speed_kmh"]=24.0
                row["charger_power_kw"]=2.0
        result=architect_cycle(eras)
        self.assertGreater(result["conflict_pct"],5)
        self.assertEqual(result["selected_next_mission"]["kind"],
                         "RESOLVE_SENSOR_CONTEXT")

    def test_insufficient_evidence_reports_waiting_not_false_success(self):
        eras=[[{"ts":1_700_000_000+j*180+i*500000,"speed_kmh":0,
                "charger_power_kw":0.0,"outside_temp_c":10.0,
                "battery_temp_c":15.0} for j in range(50)] for i in range(5)]
        result=architect_cycle(eras)
        self.assertEqual(result["status_counts"]["SHADOW_ASSOCIATION"],0)
        self.assertGreater(result["status_counts"]["INSUFFICIENT_EVIDENCE"],0)

    def test_limit_and_era_guards(self):
        with self.assertRaises(ValueError):
            architect_cycle(synthetic_blocks()[:4])
        with self.assertRaises(ValueError):
            architect_cycle(synthetic_blocks(),max_trials=100)
        with self.assertRaises(ValueError):
            historical_blocks(Path("not-real.sqlite3"),blocks=5,rows_per_block=3001)

    def test_separate_store_dryrun_and_explicit_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.sqlite3"
            previous=Path(tmp)/"previous.sqlite3"
            architect=Path(tmp)/"architect.sqlite3"
            fixture=synthetic_blocks()
            write_fixture(source, fixture)
            data=historical_blocks(source,blocks=5,rows_per_block=200)
            self.assertEqual(len(data),5)
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            result=architect_once(source,previous,architect,rows_per_block=200)
            self.assertEqual(result["stored"],False)
            self.assertFalse(architect.exists())
            self.assertFalse(previous.exists())
            saved=architect_once(source,previous,architect,save=True,rows_per_block=200)
            self.assertTrue(saved["stored"])
            self.assertEqual(saved["architect_run_id"],1)
            latest=ArchitectLedger(architect).latest()
            self.assertEqual(latest["run"]["total_trials"],len(saved["trials"]))
            self.assertEqual(len(latest["trials"]),len(saved["trials"]))
            self.assertNotIn("PRIVATE_LOCATION",json.dumps(latest))
            self.assertNotIn("SIMULATED_CAR",json.dumps(latest))
            self.assertEqual(before,hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertFalse(previous.exists())
            self.assertEqual(ArchitectLedger(architect).latest(),latest)

    def test_never_allow_source_or_previous_ledger_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.sqlite3"
            write_fixture(source,synthetic_blocks())
            with self.assertRaises(ValueError):
                architect_once(source,Path(tmp)/"previous.db",source,save=True,rows_per_block=200)
            previous=Path(tmp)/"previous.db"
            with self.assertRaises(ValueError):
                architect_once(source,previous,previous,save=True,rows_per_block=200)

if __name__=="__main__":
    unittest.main()
