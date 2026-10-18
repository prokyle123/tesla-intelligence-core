"""Product core and dashboard acceptance tests. All data here is synthetic."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from genesis.api import blueprint
from genesis.product_core import ProductLedger,run_product_cycle
from genesis.workspace import create_workspace_app


def mock_architect():
    return {
        "trials_evaluated":11,
        "status_counts":{"SHADOW_ASSOCIATION":3,
                         "CHALLENGE_FAILED":8,"INSUFFICIENT_EVIDENCE":0},
        "selected_next_mission":{
            "kind":"RESOLVE_SENSOR_CONTEXT",
            "title":"Check sensor semantics",
            "reason":"Charging and speed readings overlap"},
    }

def mock_tournament(*,status="HOLDOUT_CHALLENGE_FAILED"):
    return {
        "selected_model":"AFFINE_THERMAL",
        "status":status,
        "validation":{
            "episode_balanced_baseline_mae_c":1.1,
            "episode_balanced_model_mae_c":.9,
            "improvement_pct":15.0,"episodes_better":36,"episodes_evaluated":62},
        "historical_holdout":{
            "episode_balanced_baseline_mae_c":.55,
            "episode_balanced_model_mae_c":.53,
            "improvement_pct":3.63,"episodes_better":33,"episodes_evaluated":62},
        "episode_counts":{"training":186,
                          "selection_validation":62,"historical_holdout":62},
        "usable_episodes_complete_heater_state":17,
        "usable_episodes_unknown_heater_state":293,
        "next_mission":"Retain persistence and improve heater-state evidence.",
        "source_rows_scanned":88219,
        "holdout_episode_bootstrap_80pct_interval_c":[-0.08,0.05],
        "models_compared":[
            {
              "model":name,
              "validation_episode_balanced_mae_c":score,
              "validation_improvement_pct":round((1.1-score)/1.1*100,2),
              "validation_episodes_better":36,
              "validation_episodes_evaluated":62,
            } for name,score in (
                ("AFFINE_THERMAL",.9),("PERSISTENCE",1.1),
                ("DRIFT_ONLY",1.2),("THERMAL_ASYMMETRIC",1.3),
                ("AMBIENT_RELAXATION",1.4))
        ],
    }


class ProductReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.source=self.root/"core.sqlite3"
        with sqlite3.connect(self.source) as con:
            con.execute("CREATE TABLE telemetry(ts REAL, raw_json TEXT)")
            con.execute("INSERT INTO telemetry VALUES(?,?)",(1,"PRIVATE_ROUTE"))
        self.product=self.root/"product.sqlite3"

    def cycle(self,*,save: bool=False,status: str="HOLDOUT_CHALLENGE_FAILED"):
        with (patch("genesis.product_core.historical_blocks",
                   return_value=[[{}] for _ in range(5)]),
              patch("genesis.product_core.architect_cycle",
                   return_value=mock_architect()),
              patch("genesis.product_core.inspect_conflicts",
                   return_value={
                       "selected_followup":{"status":"REVIEW_SIGNAL_SEMANTICS"},
                       "conflicting_observations":1850,"conflict_pct":15.42}),
              patch("genesis.product_core.run_tournament",
                   return_value=mock_tournament(status=status))):
            return run_product_cycle(self.source,self.product,save=save)

    def test_manual_dryrun_creates_no_database_or_source_modification(self):
        baseline=hashlib.sha256(self.source.read_bytes()).hexdigest()
        result=self.cycle()
        self.assertFalse(result["saved"])
        self.assertEqual(result["status"],"REJECTED")
        self.assertEqual(result["thermal_holdout"]["improvement_pct"],3.63)
        self.assertFalse(self.product.exists())
        self.assertEqual(baseline,hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_completed_product_cycles_are_persisted_without_private_readings(self):
        baseline=hashlib.sha256(self.source.read_bytes()).hexdigest()
        a=self.cycle(save=True)
        b=self.cycle(save=True,status="PERSISTENCE_RETAINED")
        self.assertEqual(a["run_id"],1)
        self.assertEqual(b["run_id"],2)
        self.assertEqual(b["status"],"PERSISTENCE_RETAINED")
        history=ProductLedger(self.product).read_recent()
        self.assertEqual([row["id"] for row in history],[2,1])
        self.assertEqual(history[1]["report"]["status"],"REJECTED")
        self.assertEqual(len(history[1]["report"]["thermal_leaderboard"]),5)
        self.assertEqual(history[1]["report"]["thermal_leaderboard"][0]["model"],"AFFINE_THERMAL")
        self.assertEqual(history[1]["report"]["source_rows_scanned"],88219)
        self.assertEqual(history[1]["report"]["thermal_uncertainty"],[-0.08,0.05])
        self.assertEqual(self.product.stat().st_mode & 0o777,0o600)
        self.assertEqual(baseline,hashlib.sha256(self.source.read_bytes()).hexdigest())
        dumped=json.dumps(history)
        self.assertNotIn("PRIVATE_ROUTE",dumped)
        self.assertNotIn("raw_json",dumped)
        self.assertNotIn('"ts"',dumped)

    def test_protected_databases_and_arbitrary_report_content_refused(self):
        with self.assertRaises(ValueError):
            run_product_cycle(self.source,self.source,save=False)
        invalid={
            "status":"REJECTED","production_changes":False,
            "network_uploads":False,"can_promote":False,
            "raw_json":"SENSITIVE"
        }
        with self.assertRaisesRegex(ValueError,"Unexpected"):
            ProductLedger(self.product).save(invalid,self.source)
        self.assertFalse(self.product.exists())
        with self.assertRaises(ValueError):
            ProductLedger(self.source).save({
                "status":"REJECTED","production_changes":False,
                "network_uploads":False,"can_promote":False
            },self.source)

    def test_readonly_workspace_serves_real_local_research_history(self):
        self.cycle(save=True)
        app=create_workspace_app(data_dir=self.root)
        app.testing=True
        client=app.test_client()
        response=client.get("/genesis")
        self.assertEqual(response.status_code,200)
        self.assertIn(b"Intelligence Command Center",response.data)
        self.assertIn(b"Model Competition Lab",response.data)
        self.assertIn(b"Research Timeline",response.data)
        self.assertEqual(response.headers["Cache-Control"],"no-store")
        self.assertIn("nosniff",response.headers["X-Content-Type-Options"])
        r=client.get("/api/genesis/overview")
        self.assertEqual(r.status_code,200)
        data=r.get_json()
        self.assertEqual(len(data["product_runs"]),1)
        self.assertEqual(data["product_runs"][0]["state"],"REJECTED")
        self.assertEqual(data["architect"],{"run":None,"trials":[]})
        self.assertFalse(data["production_changes"])
        self.assertEqual(client.get("/api/genesis/health").get_json()["data_available"],True)
        self.assertEqual(client.post("/api/genesis/overview").status_code,405)
        self.assertEqual(client.post("/genesis").status_code,405)
        self.assertEqual(client.post("/api/genesis/health").status_code,405)

    def test_viewer_does_not_create_missing_ledgers(self):
        empty=self.root/"empty"
        empty.mkdir(mode=0o700)
        app=create_workspace_app(data_dir=empty)
        data=app.test_client().get("/api/genesis/overview").get_json()
        self.assertEqual(data["product_runs"],[])
        self.assertEqual(data["runs"],[])
        self.assertEqual(data["architect"],{"run":None,"trials":[]})
        self.assertEqual(list(empty.iterdir()),[])

    def test_localonly_serve_rejects_remote_binding(self):
        from genesis.workspace import main
        with self.assertRaises(SystemExit) as ctx:
            main(["--data-dir",str(self.root),"--bind","0.0.0.0"])
        self.assertEqual(ctx.exception.code,2)

if __name__=="__main__":
    unittest.main()
