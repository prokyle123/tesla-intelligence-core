"""Synthetic, offline scientific-validation regression tests."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from genesis.validation import audit_pair, retrospective_audit

def fixture(n=720):
    return [{
        "ts": 1700000000+900*i,
        "outside_temp_c": 9+10*math.sin(i*.17),
        "battery_temp_c": 17+9*math.sin(i*.17)+.2*math.sin(i*2.7),
        "battery_level": 70-i*.01,
        "speed_kmh": 20 if i%3 == 0 else 0,
        "charger_power_kw": 0.0,
    } for i in range(n)]

class GenesisValidationTests(unittest.TestCase):
    def test_historical_replication_not_prospective(self):
        finding=audit_pair(fixture(),"outside_temp_c","battery_temp_c")
        self.assertEqual(finding["folds_tested"],3)
        self.assertEqual(finding["status"],"HISTORICALLY_REPEATABLE")
        self.assertFalse(finding["eligible_for_production"])
        self.assertFalse(finding["prospective_confirmation"])
        self.assertFalse(finding["publishable_fleet_finding"])
        self.assertNotIn("ts",json.dumps(finding))

    def test_temperature_soc_warning(self):
        finding=audit_pair(fixture(),"outside_temp_c","battery_level")
        self.assertIn("TIME_AND_CHARGING_CONFOUNDING_LIKELY",finding["warnings"])
        self.assertFalse(finding["eligible_for_production"])

    def test_missing_older_history_not_faked(self):
        report=retrospective_audit(fixture(250),[("outside_temp_c","battery_temp_c")],recent_window=260)
        self.assertEqual(report["older_rows_inspected"],0)
        self.assertEqual(report["results"][0]["status"],"INSUFFICIENT_HISTORICAL_EVIDENCE")
        self.assertEqual(report["prospectively_confirmed"],0)

    def test_only_allowlisted_metrics_and_bounded_work(self):
        with self.assertRaises(ValueError):
            audit_pair(fixture(),"raw_json","battery_temp_c")
        with self.assertRaises(ValueError):
            retrospective_audit(fixture(),[("outside_temp_c","battery_temp_c")]*41,recent_window=260)
        with self.assertRaises(ValueError):
            retrospective_audit(fixture(),[],recent_window=10)

if __name__=="__main__":
    unittest.main()
