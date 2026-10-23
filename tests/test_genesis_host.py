"""Preflight must not mutate production data or produce identifiers."""
import tempfile
import sqlite3
import unittest
from pathlib import Path
from genesis.source import load_numeric_history
from scripts.genesis_host_preflight import source_meta

class HostPreflightContract(unittest.TestCase):
    def test_missing_host_db_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nonexistent.sqlite3"
            result = source_meta(p)
            self.assertEqual(result, {"present": False})
            self.assertFalse(p.exists())

    def test_meta_exposes_only_counts_not_identifiers(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "real.sqlite3"
            with sqlite3.connect(p) as con:
                con.execute("CREATE TABLE telemetry(ts REAL, car_id TEXT, raw_json TEXT)")
                con.execute("INSERT INTO telemetry VALUES(1, 'PRIVATEVIN', 'PRIVATELOCATION')")
            result = source_meta(p)
            self.assertTrue(result["readable"])
            self.assertEqual(result["telemetry_rows"], 1)
            self.assertNotIn("PRIVATEVIN", str(result))
            self.assertNotIn("PRIVATELOCATION", str(result))

if __name__ == "__main__":
    unittest.main()
