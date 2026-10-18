"""Synthetic safety/holdout checks for Genesis thermal model tournament."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genesis.thermal_tournament import tournament_from_episodes,run_tournament


def episodes(n=100, style="relaxation", change_after=None):
    result=[]
    for i in range(n):
        points=[]
        for j in range(3):
            pack=8+(i%15)*.8+j*.2
            ambient=pack-(4+i%5)
            if style=="relaxation":
                future=pack+.18*(ambient-pack)
            elif style=="drift":
                future=pack-.85
            elif style=="no_change":
                future=pack
            else:
                raise ValueError(style)
            if change_after is not None and i>=change_after:
                future=pack+.9
            future+=.002*math.sin(i+j)
            points.append((pack,ambient,future))
        result.append(points)
    return result


class ThermalTournamentTests(unittest.TestCase):
    def test_relaxation_competes_successfully_when_real_evidence_supports_it(self):
        result=tournament_from_episodes(episodes())
        self.assertEqual(result["selected_model"],"AMBIENT_RELAXATION")
        self.assertEqual(result["status"],"RESEARCH_ONLY_HISTORICAL_WIN")
        self.assertGreater(result["validation"]["improvement_pct"],10)
        self.assertGreater(result["historical_holdout"]["improvement_pct"],10)
        self.assertGreater(result["holdout_episode_bootstrap_80pct_interval_c"][0],0)
        self.assertEqual(result["episode_counts"],{
            "training":60,"selection_validation":20,"historical_holdout":20})
        self.assertFalse(result["can_promote"])
        self.assertFalse(result["automatic_model_promotion"])
        self.assertFalse(result["production_changes"])
        self.assertFalse(result["network_uploads"])
        self.assertIn("PREVIOUSLY_EXPLORED_HISTORICAL_DATA_NOT_PROSPECTIVE",result["caveats"])

    def test_no_change_baseline_must_win_no_false_positive(self):
        result=tournament_from_episodes(episodes(style="no_change"))
        self.assertEqual(result["selected_model"],"PERSISTENCE")
        self.assertEqual(result["status"],"PERSISTENCE_RETAINED")
        self.assertEqual(result["historical_holdout"]["improvement_pct"],0)

    def test_model_chosen_on_validation_does_not_get_test_tuned(self):
        result=tournament_from_episodes(episodes(
            style="relaxation",change_after=80))
        self.assertEqual(result["selected_model"],"AMBIENT_RELAXATION")
        self.assertEqual(result["status"],"HOLDOUT_CHALLENGE_FAILED")
        self.assertLess(result["historical_holdout"]["improvement_pct"],0)
        self.assertFalse(result["can_promote"])

    def test_no_eligible_episodes_does_not_invent_model(self):
        result=tournament_from_episodes(episodes(20))
        self.assertEqual(result["status"],"INSUFFICIENT_EPISODE_EVIDENCE")
        self.assertEqual(result["models_compared"],[])
        self.assertIsNone(result["historical_holdout"])
        with self.assertRaises(ValueError):
            tournament_from_episodes([[]])
        with self.assertRaises(ValueError):
            tournament_from_episodes(episodes(3001))

    def test_real_source_path_read_only_and_without_identifiers(self):
        from test_genesis_episode_lab import fixture
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"source.sqlite3"
            fixture(db,episodes=30)
            digest=hashlib.sha256(db.read_bytes()).hexdigest()
            result=run_tournament(db,max_scan=1000)
            self.assertEqual(result["source_rows_scanned"],870)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),digest)
            summary=json.dumps(result)
            self.assertNotIn("SIMULATED_PRIVATE",summary)
            self.assertNotIn("DO_NOT_EXPORT_ROUTE",summary)
            self.assertNotIn('"ts"',summary)
            self.assertFalse(result["can_promote"])

if __name__=="__main__":
    unittest.main()
