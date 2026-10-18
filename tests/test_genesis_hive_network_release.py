"""HIVE real-data deletion, quarantined model summaries and public-page safety."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from genesis.hive_server import create_app,enroll
from genesis.hive_models import validate_model_manifest,ModelMetadataError
from genesis.hive_public import summary

ROOT=Path(__file__).resolve().parents[1]


class HiveNetworkReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.root.chmod(0o700)
        self.db=self.root/"hub.sqlite3"
        self.client=create_app(self.db).test_client()
        self.token=enroll(self.db)
        self.auth={"Authorization":"Bearer "+self.token}

    def test_approved_manifest_only_and_never_executable_weights(self):
        manifest={"schema":"ghost-hive-model-manifest-v1",
                  "family":"pack_temp_60m","backend":"tree",
                  "validation_rows":500,"mae":1.113,
                  "mae_unit":"C","evaluation":"out_of_time_historical",
                  "version":"ghost-v1"}
        self.assertEqual(validate_model_manifest(manifest),manifest)
        for field in ("weights","path","file","vin","gps","raw_data","token"):
            with self.assertRaises(ModelMetadataError):
                validate_model_manifest({**manifest,field:"PRIVATE"})
        self.assertEqual(self.client.post("/v1/model-manifests",json=manifest).status_code,401)
        ok=self.client.post("/v1/model-manifests",json=manifest,headers=self.auth)
        self.assertEqual(ok.status_code,202)
        self.assertEqual(ok.get_json()["status"],"QUARANTINED_METADATA_ONLY")
        self.assertFalse(ok.get_json()["weights_uploaded"])
        self.assertFalse(ok.get_json()["production_promotion"])
        with sqlite3.connect(self.db) as con:
            row=con.execute("SELECT manifest_json FROM model_manifests").fetchone()
        self.assertEqual(json.loads(row[0]),manifest)

    def test_self_service_removal_erases_all_source_specific_information(self):
        research={"schema":"ghost-hive-monthly-v1",
                  "metric":"ghost-battery-temp-forecast-mae-v1",
                  "month":"2026-10","scored_predictions":40,
                  "total_abs_error_c":20.5,"source":"ghost_prediction_audit"}
        model={"schema":"ghost-hive-model-manifest-v1",
               "family":"trip_energy_kwh","backend":"pytorch",
               "validation_rows":250,"mae":2.3,"mae_unit":"kwh",
               "evaluation":"out_of_time_historical","version":"ghost-v1"}
        self.assertEqual(self.client.post("/v1/monthly-research",
                         json=research,headers=self.auth).status_code,202)
        self.assertEqual(self.client.post("/v1/model-manifests",
                         json=model,headers=self.auth).status_code,202)
        removed=self.client.delete("/v1/enrollment",headers=self.auth)
        self.assertEqual(removed.status_code,200)
        self.assertTrue(removed.get_json()["contributions_erased"])
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM monthly_research").fetchone()[0],0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM model_manifests").fetchone()[0],0)
        self.assertEqual(self.client.post("/v1/monthly-research",
                         json=research,headers=self.auth).status_code,401)
        self.assertEqual(self.client.get("/v1/public-network").get_json()["reporting_nodes"],0)

    def test_static_public_page_only_consumes_sanitized_schema(self):
        html=(ROOT/"docs/hive/index.html").read_text()
        data=json.loads((ROOT/"docs/hive/network.json").read_text())
        self.assertIn("GHOST <span>HIVE</span>",html)
        self.assertIn("./network.json",html)
        self.assertNotIn("/api/hive/local",html)
        self.assertNotIn("127.0.0.1:8766",html)
        self.assertNotIn("<nav",html)
        self.assertEqual(data["reporting_nodes"],0)
        self.assertIsNone(data["mean_error_f"])
        self.assertIsNone(data["fleet_accuracy_percent"])
        self.assertFalse(data["model_weights_shared"])
        self.assertEqual(data["regions"],[])

    def test_public_export_matches_api_and_hides_small_group_detail(self):
        first=enroll(self.db)
        r={"schema":"ghost-hive-monthly-v1",
           "metric":"ghost-battery-temp-forecast-mae-v1",
           "month":"2026-10","scored_predictions":50,
           "total_abs_error_c":25.00,"source":"ghost_prediction_audit"}
        self.assertEqual(self.client.post("/v1/monthly-research",json=r,
                         headers={"Authorization":"Bearer "+first}).status_code,202)
        data=summary(self.db)
        self.assertEqual(data["reporting_nodes"],1)
        self.assertIsNone(data["mean_error_f"])
        self.assertIsNone(data["predictions_checked"])
        self.assertFalse(data["verified_unique_people"])
        self.assertEqual(data["countries"],None)
        self.assertEqual(data["regions"],[])
        self.assertNotIn(self.token,json.dumps(data))


if __name__=="__main__":
    unittest.main()
