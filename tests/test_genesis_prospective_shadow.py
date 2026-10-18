"""Post-freeze shadow: independent future episodes, privacy, immutability.

All values here are synthetic. No route identifiers or raw observations
can be stored in the separate research-only ledger.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from genesis.prospective_shadow import (
    freeze_shadow, score_shadow, shadow_status, _load_freeze,
    _new_completed_episodes
)
from genesis.source import SourceUnavailable
from test_genesis_episode_lab import fixture


def append_future(db: Path, start: float, count: int=12,
                  heater_unknown: bool=False, leave_last_open: bool=False):
    rows=[]
    for episode in range(count):
        base=start + 100 + episode*19000
        # A real observed nonparked boundary before EACH parked episode.
        rows.append((base-60,"SIMULATED_PRIVATE","PRIVATE_ROUTE",25.0,0.0,
                     7.0,18.0,0.0,0.0))
        ambient=4 + episode%7
        initial=ambient+11.0
        for i in range(29):
            future=ambient+(initial-ambient)*math.exp(-.24*i*300/3600)
            rows.append((base+i*300,"SIMULATED_PRIVATE","PRIVATE_ROUTE",
                         0.0,0.0,float(ambient),future,
                         None if heater_unknown else 0.0,0.0))
        if not (leave_last_open and episode==count-1):
            rows.append((base+29*300,"SIMULATED_PRIVATE","PRIVATE_ROUTE",
                         25.0,0.0,7.0,18.0,0.0,0.0))
    with sqlite3.connect(db) as con:
        con.executemany("INSERT INTO telemetry VALUES(?,?,?,?,?,?,?,?,?)",rows)
    return rows[-1][0]


class ProspectiveShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/"source.sqlite3"
        self.state=Path(self.tmp.name)/"shadow.sqlite3"
        fixture(self.source,episodes=30)

    def test_freeze_is_one_time_and_does_not_modify_telemetry(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        report=freeze_shadow(self.source,self.state,max_scan=1000)
        self.assertEqual(report["status"],"FROZEN_DIAGNOSTIC_ONLY")
        self.assertFalse(report["can_promote"])
        self.assertTrue(self.state.exists())
        self.assertEqual(self.state.stat().st_mode & 0o777,0o600)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)
        with self.assertRaisesRegex(ValueError,"already frozen"):
            freeze_shadow(self.source,self.state,max_scan=1000)
        self.assertNotIn("PRIVATE_ROUTE",json.dumps(report))
        self.assertNotIn("SIMULATED_PRIVATE",json.dumps(report))

    def test_no_pre_freeze_data_leaks_and_no_open_tail_is_scored(self):
        freeze_shadow(self.source,self.state,max_scan=1000)
        frozen=_load_freeze(self.state,self.source)
        before=score_shadow(self.source,self.state,max_scan=1000)
        self.assertEqual(before["completed_post_freeze_episodes"],0)
        end=append_future(self.source,frozen["cutoff_ts"]+200,11,
                          leave_last_open=True)
        value=score_shadow(self.source,self.state,max_scan=1000,now=end+100)
        self.assertEqual(value["completed_post_freeze_episodes"],10)
        self.assertGreater(value["post_freeze_hourly_pairs"],20)
        self.assertGreater(value["excluded_incomplete_tail_rows"],0)
        self.assertFalse(value["can_promote"])
        self.assertFalse(value["production_changes"])
        self.assertFalse(value["network_uploads"])

    def test_completed_future_episodes_score_and_deduplicate_check(self):
        freeze_shadow(self.source,self.state,max_scan=1000)
        cutoff=_load_freeze(self.state,self.source)["cutoff_ts"]
        end=append_future(self.source,cutoff+200,12)
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        first=score_shadow(self.source,self.state,max_scan=1000,now=end+100)
        self.assertEqual(first["completed_post_freeze_episodes"],12)
        self.assertGreater(first["post_freeze_hourly_pairs"],20)
        self.assertTrue(first["new_summary_recorded"])
        self.assertIsInstance(first["improvement_pct"],float)
        again=score_shadow(self.source,self.state,max_scan=1000,now=end+100)
        self.assertFalse(again["new_summary_recorded"])
        self.assertEqual(first["improvement_pct"],again["improvement_pct"])
        last=shadow_status(self.state,self.source)
        self.assertEqual(last["summary_checks_recorded"],1+1)
        self.assertFalse(last["can_promote"])
        self.assertEqual(digest,hashlib.sha256(self.source.read_bytes()).hexdigest())
        raw=json.dumps(last)
        self.assertNotIn("PRIVATE_ROUTE",raw)
        self.assertNotIn("SIMULATED_PRIVATE",raw)
        self.assertNotIn('"ts"',raw)

    def test_incomplete_heater_is_not_allowed_to_claim_clear_result(self):
        freeze_shadow(self.source,self.state,max_scan=1000)
        cutoff=_load_freeze(self.state,self.source)["cutoff_ts"]
        end=append_future(self.source,cutoff+200,12,heater_unknown=True)
        result=score_shadow(self.source,self.state,max_scan=1000,now=end+100)
        self.assertEqual(result["status"],"SHADOW_SCORE_HEATER_UNVERIFIED")
        self.assertEqual(result["heater_verified_episodes"],0)
        self.assertEqual(result["heater_unverified_episodes"],12)
        self.assertFalse(result["can_promote"])

    def test_reject_other_sources_tampering_and_invalid_scans(self):
        freeze_shadow(self.source,self.state,max_scan=1000)
        another=Path(self.tmp.name)/"another.sqlite3"
        fixture(another,episodes=30)
        with self.assertRaisesRegex(ValueError,"another source"):
            shadow_status(self.state,another)
        with self.assertRaises(ValueError):
            score_shadow(self.source,self.state,max_scan=120001)
        with sqlite3.connect(self.state) as con:
            con.execute("UPDATE frozen_shadow SET parameters_json=?",('{"alpha":0,"bias":0}',))
        with self.assertRaisesRegex(ValueError,"integrity"):
            shadow_status(self.state,self.source)

    def test_uninitialized_file_and_missing_source_fail_closed(self):
        with self.assertRaises(SourceUnavailable):
            shadow_status(self.state,self.source)
        with self.assertRaises(SourceUnavailable):
            freeze_shadow(Path(self.tmp.name)/"missing.sqlite3",self.state,max_scan=1000)
        self.assertFalse(self.state.exists())
        with self.assertRaises(ValueError):
            freeze_shadow(self.source,self.source,max_scan=1000)

    def test_scan_budget_fails_without_partial_summary(self):
        freeze_shadow(self.source,self.state,max_scan=1000)
        cutoff=_load_freeze(self.state,self.source)["cutoff_ts"]
        end=append_future(self.source,cutoff+200,38)
        with self.assertRaisesRegex(SourceUnavailable,"capacity"):
            score_shadow(self.source,self.state,max_scan=1000,now=end+100)
        status=shadow_status(self.state,self.source)
        self.assertEqual(status["summary_checks_recorded"],0)

if __name__=="__main__":
    unittest.main()
