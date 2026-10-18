"""Safety and evidence tests for GENESIS using synthetic data only."""
from __future__ import annotations
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genesis.cli import overview, run_once
from genesis.config import enabled
from genesis.hivemind import MIN_COHORT, PrivacyGate, SyntheticClientMetric, network_status, simulate_cohort
from genesis.research import discover
from genesis.source import SourceUnavailable, load_numeric_history
from genesis.store import ResearchStore

ROOT = Path(__file__).resolve().parent.parent

def fixture(path: Path, other_car: bool = False) -> None:
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE telemetry (
            ts REAL, car_id TEXT, raw_json TEXT, outside_temp_c REAL,
            battery_temp_c REAL, speed_kmh REAL, power_kw REAL,
            module_temp_spread_c REAL, pack_current_abs_a REAL,
            charger_power_kw REAL, battery_level REAL
        )""")
        rows = []
        for i in range(520):
            outside = 8.0 + 9 * math.sin(i * .19)
            temp = 16 + outside * .85 + .18 * math.sin(i * 3)
            speed = 20 + 12 * math.sin(i * .13)
            rows.append((1700000000 + i * 900, "TEST_CAR", "SECRET_LOCATION_DO_NOT_EXPOSE",
                outside, temp, speed, speed * .12, abs(math.sin(i)) * 2,
                14 + math.sin(i), .9, 65 - i * .007))
        con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        if other_car:
            con.execute("INSERT INTO telemetry(ts,car_id) VALUES(?,?)", (1800000000, "SECOND_CAR"))
        con.commit()

class GenesisPrivacyAndDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.core = self.directory / "core.sqlite3"
        self.research = self.directory / "genesis" / "research.sqlite3"
        fixture(self.core)

    def test_source_read_only_and_excludes_private_fields(self):
        before = hashlib.sha256(self.core.read_bytes()).hexdigest()
        rows = load_numeric_history(self.core)
        self.assertGreater(len(rows), 400)
        self.assertTrue(set(rows[0]).issubset({
            "ts", "outside_temp_c", "battery_temp_c", "speed_kmh", "power_kw",
            "module_temp_spread_c", "pack_current_abs_a", "charger_power_kw",
            "battery_level",
        }))
        self.assertNotIn("raw_json", str(rows))
        self.assertNotIn("car_id", str(rows))
        self.assertNotIn("SECRET_LOCATION_DO_NOT_EXPOSE", str(rows))
        self.assertEqual(before, hashlib.sha256(self.core.read_bytes()).hexdigest())

    def test_multiple_cars_fail_closed(self):
        other = self.directory / "multi.sqlite3"
        fixture(other, other_car=True)
        with self.assertRaisesRegex(SourceUnavailable, "Multiple vehicles"):
            load_numeric_history(other)
        self.assertFalse(self.research.exists())

    def test_missing_source_not_created(self):
        missing = self.directory / "missing.sqlite3"
        with self.assertRaises(SourceUnavailable):
            load_numeric_history(missing)
        self.assertFalse(missing.exists())

    def test_temporal_holdout_and_shadow_only(self):
        found = discover(load_numeric_history(self.core))
        self.assertGreater(len(found), 4)
        matches = [f for f in found if f.target == "battery_temp_c" and f.feature == "outside_temp_c"]
        self.assertEqual(len(matches), 1)
        h = matches[0]
        self.assertEqual(h.status, "SHADOW")
        self.assertGreater(h.improvement_pct, 10)
        self.assertGreater(h.train_rows, 90)
        self.assertGreater(h.test_rows, 30)
        self.assertFalse(set(h.public_summary()) & {"car_id", "ts", "raw_json"})
        self.assertTrue(all(f.status in {"SHADOW", "REJECTED"} for f in found))

    def test_research_cycle_preserves_core_file_and_private_data(self):
        digest = hashlib.sha256(self.core.read_bytes()).hexdigest()
        result = run_once(self.core, self.research)
        self.assertGreater(result["evaluated"], 0)
        self.assertFalse(result["production_changes"])
        self.assertFalse(result["hivemind_uploads"])
        self.assertTrue(self.research.is_file())
        self.assertEqual(digest, hashlib.sha256(self.core.read_bytes()).hexdigest())
        self.assertEqual(ResearchStore(self.research).recent_runs()[0]["id"], result["run_id"])
        public = json.dumps(overview(self.research))
        for private in ("SECRET_LOCATION_DO_NOT_EXPOSE", "TEST_CAR", "raw_json", "vin"):
            self.assertNotIn(private.lower(), public.lower())

    def test_discovery_reporting_prioritizes_shadows_without_losing_rejections(self):
        from genesis.cli import latest_discoveries
        original = discover(load_numeric_history(self.core))
        self.assertTrue(any(x.status == "SHADOW" for x in original))
        # Store 40 experiments with the rejected results at the end,
        # reproducing the actual first-Pi-cycle reporting bug.
        accepted = [x for x in original if x.status == "SHADOW"]
        rejected = [x for x in original if x.status == "REJECTED"]
        # Extend the synthetic fixture with rejected candidates to reproduce
        # the real-world result (32 rejects hid 8 accepted discoveries).
        rejected.extend(rejected[:max(0, 26 - len(rejected))])
        ordered = accepted + rejected
        self.assertGreater(len(ordered), 25)
        self.assertGreater(len(rejected), 25)
        store = ResearchStore(self.research)
        store.save(self.core, 6000, ordered)
        report = overview(self.research)
        self.assertTrue(report["findings"])
        self.assertEqual(report["findings"][0]["status"], "SHADOW")
        self.assertEqual(
            sum(item["status"] == "SHADOW" for item in report["findings"]),
            len([x for x in ordered if x.status == "SHADOW"]))
        findings = latest_discoveries(self.research)
        self.assertEqual(findings["evaluated"], len(ordered))
        self.assertEqual(findings["shadow_candidates"], len(findings["findings"]))
        self.assertTrue(all(x["status"] == "SHADOW" for x in findings["findings"]))
        self.assertNotIn("car_id", json.dumps(findings))
        # A later run must supersede the previous results rather than mixing them.
        store.save(self.core, 0, [])
        self.assertEqual(latest_discoveries(self.research)["findings"], [])
        self.assertEqual(overview(self.research)["findings"], [])

    def test_store_refuses_core_database(self):
        with self.assertRaisesRegex(ValueError, "production"):
            ResearchStore(self.core).save(self.core, 0, [])
        with self.assertRaisesRegex(ValueError, "production"):
            run_once(self.core, self.core)

    def test_fleet_network_always_disabled_even_requested(self):
        with patch.dict(os.environ, {"GHOST_HIVEMIND_MODE": "off"}):
            self.assertEqual(network_status()["mode"], "off")
        with patch.dict(os.environ, {"GHOST_HIVEMIND_MODE": "contribute"}):
            status = network_status()
            self.assertFalse(status["network_enabled"])
            self.assertFalse(status["outbound_uploads"])
            self.assertFalse(status["global_models_enabled"])

    def test_fake_cohort_threshold_is_not_privacy_protection(self):
        with self.assertRaises(PrivacyGate):
            simulate_cohort([SyntheticClientMetric(10, 12)] * (MIN_COHORT - 1))
        summary = simulate_cohort([SyntheticClientMetric(10, 12)] * MIN_COHORT)
        self.assertFalse(summary["publishable"])
        self.assertTrue(summary["simulation"])
        self.assertNotIn("vehicle", summary)

    def test_optional_ui_disabled_and_classic_untouched(self):
        with patch.dict(os.environ, {"GHOST_GENESIS_ENABLED": "false"}):
            self.assertFalse(enabled())
        with patch.dict(os.environ, {"GHOST_GENESIS_ENABLED": "true"}):
            self.assertTrue(enabled())
        server = (ROOT / "ghost_tesla_ai/server.py").read_text()
        self.assertIn("if genesis_config.enabled():", server)
        self.assertIn("app.register_blueprint(genesis_bp)", server)
        self.assertGreater((ROOT / "web/templates/index.html").stat().st_size, 100000)

    def test_installer_installs_code_without_genesis_timers(self):
        installer = (ROOT / "install.sh").read_text()
        self.assertIn('$SUDO cp -a "$ROOT/genesis" "$INSTALL_DIR/"', installer)
        self.assertFalse(list((ROOT / "systemd/templates").glob("*genesis*")))

if __name__ == "__main__":
    unittest.main()
