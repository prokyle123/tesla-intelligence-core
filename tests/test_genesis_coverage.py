"""Regime quality gates: missing values, conflicts and discontinuities."""
from __future__ import annotations
import json
import unittest

from genesis.coverage import classify_regime,coverage_report
from genesis.validation import _differences

class GenesisCoverageTests(unittest.TestCase):
    def test_missing_values_do_not_imply_parked(self):
        self.assertEqual(classify_regime({}),"UNKNOWN")
        self.assertEqual(classify_regime({"speed_kmh":None,"charger_power_kw":0}),"UNKNOWN")
        self.assertEqual(classify_regime({"speed_kmh":0,"charger_power_kw":None}),"UNKNOWN")
        self.assertEqual(classify_regime({"speed_kmh":0,"charger_power_kw":0}),"PARKED_OR_OTHER")
        self.assertEqual(classify_regime({"speed_kmh":12,"charger_power_kw":0}),"DRIVING")
        self.assertEqual(classify_regime({"speed_kmh":0,"charger_power_kw":1.0}),"CHARGING")
        self.assertEqual(classify_regime({"speed_kmh":12,"charger_power_kw":1.0}),"CONFLICT")
        self.assertEqual(classify_regime({"speed_kmh":0,"charge_input_kw":0.9}),"CHARGING")

    def test_coverage_counts_and_no_sensitive_values(self):
        rows=[{
            "ts":1_700_000_000+i*900,
            "speed_kmh":0,
            "charger_power_kw":1,
            "outside_temp_c":8+i*.01,
            "battery_temp_c":10+i*.02,
            "raw_json":"AN_ULTRA_PRIVATE_ROUTE",
            "car_id":"PRIVATE_CAR",
        } for i in range(320)]
        report=coverage_report(rows,[("outside_temp_c","battery_temp_c")])
        self.assertEqual(report["raw_regime_counts"]["CHARGING"],320)
        self.assertEqual(report["thinned_regime_counts"]["DRIVING"],0)
        self.assertEqual(report["candidate_pair_coverage"][0]["paired_samples"],320)
        self.assertIn("SINGLE_REGIME_DOMINATES_USABLE_EVIDENCE",report["warnings"])
        out=json.dumps(report)
        for sensitive in ("AN_ULTRA_PRIVATE_ROUTE","PRIVATE_CAR","car_id","raw_json"):
            self.assertNotIn(sensitive,out)
        self.assertFalse(report["can_publish_to_fleet"])

    def test_charging_does_not_supply_driving_evidence(self):
        rows=[{"ts":1_700_000_000+i*900,"speed_kmh":0,"charger_power_kw":1,
               "outside_temp_c":i*.01,"battery_temp_c":i*.02} for i in range(310)]
        report=coverage_report(rows)
        self.assertEqual(report["thinned_regime_counts"]["CHARGING"],310)
        self.assertEqual(report["thinned_regime_counts"]["PARKED_OR_OTHER"],0)

    def test_delta_discontinuities_and_regime_switches_not_computed(self):
        rows=[
            {"ts":1000,"outside_temp_c":5,"battery_temp_c":10,"speed_kmh":0,"charger_power_kw":0},
            {"ts":1900,"outside_temp_c":6,"battery_temp_c":11,"speed_kmh":0,"charger_power_kw":0},
            {"ts":10000,"outside_temp_c":7,"battery_temp_c":12,"speed_kmh":0,"charger_power_kw":0},
            {"ts":10900,"outside_temp_c":8,"battery_temp_c":13,"speed_kmh":20,"charger_power_kw":0},
            {"ts":11800,"outside_temp_c":9,"battery_temp_c":14,"speed_kmh":30,"charger_power_kw":0},
            {"ts":12700,"outside_temp_c":10,"battery_temp_c":15,"speed_kmh":0,"charger_power_kw":1},
        ]
        self.assertEqual(_differences(rows,"outside_temp_c","battery_temp_c"),[(1.0,1.0),(1.0,1.0)])

    def test_disallowed_pair_refused(self):
        with self.assertRaises(ValueError):
            coverage_report([], [("raw_json","battery_temp_c")])
        with self.assertRaises(ValueError):
            coverage_report([], [("outside_temp_c","battery_temp_c")]*41)

if __name__=="__main__":
    unittest.main()
