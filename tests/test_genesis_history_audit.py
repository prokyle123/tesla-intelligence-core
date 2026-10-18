"""Distributed history audit: bounded, private and read-only."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from genesis.history_audit import distributed_coverage
from genesis.source import SourceUnavailable

def generate_db(path: Path, second_car: bool = False):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE telemetry (
            ts REAL, car_id TEXT, raw_json TEXT, speed_kmh REAL,
            charger_power_kw REAL, outside_temp_c REAL,
            battery_temp_c REAL, battery_level REAL)""")
        rows = []
        for i in range(2000):
            if i < 400 or i >= 1300:
                speed, charge = 35.0, 0.0
            elif i < 900:
                speed, charge = 0.0, 0.0
            else:
                speed, charge = 0.0, 4.5
            rows.append((1_700_000_000 + 60*i,"synthetic-primary",
                         "PRIVATE_ROUTE_NEVER_REPORT",speed,charge,
                         8.0+i*.01,10.0+i*.01,70.0-i*.002))
        con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?)",rows)
        if second_car:
            con.execute("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?)",
                        (1_700_500_000,"synthetic-other","PRIVATE_ROUTE",0,0,8,10,50))

class DistributedCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/"source.sqlite3"
        generate_db(self.db)

    def test_separated_eras_capture_regime_diversity(self):
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = distributed_coverage(self.db,
                 [("outside_temp_c","battery_temp_c")],
                 blocks=4,rows_per_block=200)
        self.assertEqual(result["source_records_total"],2000)
        self.assertEqual(result["records_inspected"],800)
        self.assertEqual(result["historical_blocks"],4)
        self.assertEqual(result["summary_regime_counts"]["DRIVING"],400)
        self.assertEqual(result["summary_regime_counts"]["CHARGING"],200)
        self.assertEqual(result["summary_regime_counts"]["PARKED_OR_OTHER"],200)
        self.assertEqual(result["blocks"][0]["raw_regime_counts"]["DRIVING"],200)
        self.assertEqual(result["blocks"][-1]["raw_regime_counts"]["DRIVING"],200)
        self.assertGreater(result["summary_pair_coverage"][0]["paired_regime_counts"]["CHARGING"],0)
        self.assertEqual(digest,hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertFalse(result["raw_values_included"])
        self.assertFalse(result["fleet_uploads"])
        self.assertFalse(result["model_validated"])
        self.assertFalse(result["eligible_for_production"])
        full=json.dumps(result)
        for value in ("PRIVATE_ROUTE_NEVER_REPORT","synthetic-primary","car_id","raw_json"):
            self.assertNotIn(value,full)

    def test_guarded_row_budget(self):
        for options in ({"blocks":5,"rows_per_block":3000},
                        {"blocks":7,"rows_per_block":100},
                        {"blocks":3,"rows_per_block":25}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                distributed_coverage(self.db,**options)

    def test_source_missing_does_not_create_database(self):
        missing=Path(self.temp.name)/"missing.sqlite3"
        with self.assertRaises(SourceUnavailable):
            distributed_coverage(missing)
        self.assertFalse(missing.exists())

    def test_mixed_vehicle_fails_closed(self):
        multiple=Path(self.temp.name)/"two.sqlite3"
        generate_db(multiple,second_car=True)
        with self.assertRaisesRegex(SourceUnavailable,"Multiple vehicles"):
            distributed_coverage(multiple,blocks=2,rows_per_block=200)

    def test_metric_allowlist_rejects_private_fields(self):
        with self.assertRaises(ValueError):
            distributed_coverage(self.db,[("raw_json","battery_temp_c")],
                                 blocks=2,rows_per_block=200)

    def test_cli_can_read_status_ledger_without_writing(self):
        from genesis.cli import historical_coverage
        target=Path(self.temp.name)/"not-created.sqlite3"
        result=historical_coverage(self.db,target,blocks=2,rows_per_block=200)
        self.assertEqual(result["historical_blocks"],2)
        self.assertEqual(result["summary_pair_coverage"],[])
        self.assertFalse(target.exists())

if __name__ == "__main__":
    unittest.main()
