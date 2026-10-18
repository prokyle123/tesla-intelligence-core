"""Hourly Hive transfer acceptance: explicit consent, fail-closed, replace-only."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from genesis import hive_member as member, hive_hourly as sync

class HourlyHiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.chmod(0o700)
        self.state=self.root/"consent"
        self.credential=self.root/"enroll"
        self.credential.write_text("S"*64)
        self.credential.chmod(0o600)
        self.source=self.root/"read-only.sqlite3"
        self.source.write_bytes(b"dummy source")
        self.payload={
            "schema":"ghost-hive-monthly-v1",
            "metric":"ghost-battery-temp-forecast-mae-v1",
            "month":"2026-10","scored_predictions":25,
            "total_abs_error_c":15.1,"source":"ghost_prediction_audit"
        }
        self.sends=[]
        member.configure(self.state,"http://127.0.0.1:8778",self.credential)
        self.pr=patch.object(member,"preview",side_effect=self.preview)
        self.pr.start()
        self.addCleanup(self.pr.stop)
        self.sender=patch.object(member,"send",side_effect=self.send)
        self.sender.start()
        self.addCleanup(self.sender.stop)

    def preview(self,source,*,month):
        return {"eligible":True,"month":month,
                "scored_predictions":self.payload["scored_predictions"],
                "payload":dict(self.payload)}
    def send(self,root,source,*,month,confirm):
        self.assertEqual(member._config(root)["mode"],"OPTED_IN")
        self.assertTrue(confirm)
        self.sends.append(month)
        return {"sent":True,"month":month}

    def test_hourly_is_off_until_informed_consent(self):
        result=sync.run_once(self.state,self.source,month="2026-10")
        self.assertEqual(result["state"],"CONSENT_OFF")
        member.consent(self.state,acknowledged=True)
        self.assertFalse(member.status(self.state)["automatic_uploads"])
        self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"CONSENT_OFF")
        self.assertEqual(self.sends,[])
        member.consent(self.state,acknowledged=True,hourly=True)
        self.assertTrue(member.status(self.state)["automatic_uploads"])
        self.assertEqual(member.status(self.state)["transfer_frequency"],"hourly")
        self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"ACCEPTED")
        self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"UNCHANGED")
        self.assertEqual(self.sends,["2026-10"])
        self.payload["scored_predictions"]=26
        self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"ACCEPTED")
        self.assertEqual(self.sends,["2026-10","2026-10"])
        self.assertEqual((self.state/"hourly-sync.json").stat().st_mode & 0o777,0o600)
        member.disable(self.state)
        self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"CONSENT_OFF")
        self.assertEqual(self.sends,["2026-10","2026-10"])

    def test_failure_does_not_advance_success_marker(self):
        member.consent(self.state,acknowledged=True,hourly=True)
        self.sender.stop()
        self.sender=patch.object(member,"send",side_effect=member.ConsentError("test network down"))
        self.sender.start()
        with self.assertRaises(member.ConsentError):
            sync.run_once(self.state,self.source,month="2026-10")
        self.assertFalse((self.state/"hourly-sync.json").exists())

    def test_lock_disallows_simultaneous_runs(self):
        import fcntl
        self.state.mkdir(exist_ok=True)
        fd=(self.state/".hourly-worker.lock").open("w")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            self.assertEqual(sync.run_once(self.state,self.source,month="2026-10")["state"],"ALREADY_RUNNING")
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
            fd.close()

    def test_timer_contract_preserves_local_off_boundary(self):
        src=(Path(__file__).resolve().parents[1]/"scripts/hive_hourly_timer.sh").read_text()
        self.assertIn("OnCalendar=hourly",src)
        self.assertIn("User=$owner",src)
        self.assertIn("-m genesis.hive_hourly",src)
        self.assertNotIn("ghost-tesla-ai-web.service",src)
        self.assertNotIn("ghost-tesla-ai-collector.service",src)
        self.assertNotIn("hive_member send",src)

if __name__=="__main__":
    unittest.main()
