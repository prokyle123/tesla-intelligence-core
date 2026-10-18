"""Hive consent UI security and exact report two-step operator workflow."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from ghost_tesla_ai import hive_local

TEST_ORIGIN="http://localhost:8766"
class HiveConsentApiTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.root.chmod(0o700)
        self.secret="Z"*64
        self.key=self.root/"dashboard-admin.token"
        self.key.write_text(self.secret)
        self.key.chmod(0o600)
        self.app=Flask("hive-consent-test")
        self.app.register_blueprint(hive_local.bp)
        self.app.testing=True
        self.client=self.app.test_client()
        self.env=patch.dict(os.environ,{"GHOST_HIVE_CLIENT_STATE_DIR":str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.work=patch.object(hive_local,"_run_hive_action",side_effect=self.worker)
        self.work.start()
        self.addCleanup(self.work.stop)
        self.operations=[]
        self.sample={
            "schema":"ghost-hive-monthly-v1",
            "metric":"ghost-battery-temp-forecast-mae-v1",
            "month":"2026-10","scored_predictions":30,
            "total_abs_error_c":42.25,
            "source":"ghost_prediction_audit",
        }

    def worker(self,action,*,month=None):
        self.operations.append((action,month))
        if action=="preview":
            return {"eligible":True,"payload":self.sample,"month":"2026-10"}
        if action=="send":
            return {"sent":True,"month":month,"received":"ACCEPTED_BY_COORDINATOR"}
        if action=="consent":
            return {"mode":"OPTED_IN","automatic_uploads":False}
        if action=="join":
            return {"mode":"OPTED_IN","automatic_uploads":True}
        if action=="disable":
            return {"mode":"OFF"}
        if action=="revoke":
            return {"disabled_locally":True,"remote_deleted":True}
        raise AssertionError(action)

    def submit(self,action,data,*,key=None,origin=TEST_ORIGIN,content_type="application/json"):
        headers={"Origin":origin,"X-Ghost-Hive-Owner":self.secret if key is None else key}
        return self.client.post("/api/hive/control/"+action,json=data,headers=headers,
                                base_url=TEST_ORIGIN) if content_type=="application/json" else self.client.post(
                                "/api/hive/control/"+action,data=json.dumps(data),
                                content_type=content_type,headers=headers,base_url=TEST_ORIGIN)

    def test_missing_or_wrong_key_origin_and_method_fail_without_worker(self):
        self.assertEqual(self.submit("consent",{"acknowledge_pseudonymous_sharing":True},key="BAD"*20).status_code,403)
        self.assertEqual(self.submit("consent",{"acknowledge_pseudonymous_sharing":True},origin="https://other.example").status_code,403)
        self.assertEqual(self.submit("consent",{"acknowledge_pseudonymous_sharing":True},content_type="text/plain").status_code,403)
        self.assertEqual(self.client.get("/api/hive/control/preview").status_code,405)
        self.assertEqual(self.operations,[])
        self.key.chmod(0o644)
        self.assertEqual(self.submit("consent",{"acknowledge_pseudonymous_sharing":True}).status_code,403)
        self.key.chmod(0o600)

    def test_consent_preview_send_are_separate_and_hash_binds_report(self):
        self.assertEqual(self.submit("consent",{}).status_code,400)
        self.assertEqual(self.operations,[])
        preview=self.submit("preview",{"month":"2026-10"})
        self.assertEqual(preview.status_code,200)
        digest=preview.get_json()["preview_sha256"]
        self.assertEqual(len(digest),64)
        self.assertNotIn("Z"*40,json.dumps(preview.get_json()))
        self.assertEqual(self.submit("send",{"month":"2026-10","preview_sha256":digest}).status_code,400)
        self.assertEqual(self.submit("send",{"month":"2026-10","preview_sha256":"0"*64,"confirm_this_exact_report":True}).status_code,409)
        self.assertEqual(self.submit("consent",{"acknowledge_pseudonymous_sharing":True}).status_code,200)
        accepted=self.submit("send",{"month":"2026-10","preview_sha256":digest,"confirm_this_exact_report":True})
        self.assertEqual(accepted.status_code,200)
        self.assertTrue(accepted.get_json()["sent"])
        self.assertEqual(self.operations[-1],("send","2026-10"))

    def test_monthly_changes_prevent_unreviewed_upload(self):
        old=self.submit("preview",{"month":"2026-10"}).get_json()["preview_sha256"]
        self.sample["scored_predictions"]=31
        failed=self.submit("send",{"month":"2026-10","confirm_this_exact_report":True,"preview_sha256":old})
        self.assertEqual(failed.status_code,409)
        self.assertNotIn(("send","2026-10"),self.operations)
        self.assertEqual(self.submit("preview",{"month":"2026-10-17"}).status_code,400)

    def test_off_and_revoke_require_owner_and_delete_confirmation(self):
        self.assertEqual(self.submit("disable",{}).get_json()["mode"],"OFF")
        self.assertEqual(self.submit("revoke",{}).status_code,400)
        self.assertEqual(self.submit("revoke",{"confirmation":"DELETE"}).get_json()["remote_deleted"],True)
        self.assertEqual(self.operations[-1],("revoke",None))


    def test_ssh_tunnel_consent_without_browser_token(self):
        req={"acknowledge_pseudonymous_sharing":True,
             "allow_hourly_aggregates":True}
        self.assertEqual(self.submit("join",{"acknowledge_pseudonymous_sharing":True}).status_code,400)
        self.assertEqual(self.submit("join",req).get_json()["automatic_uploads"],True)
        local="http://127.0.0.1:8766"
        self.operations.clear()
        ok=self.client.post("/api/hive/control/join",json=req,
            headers={"Origin":local},base_url=local,
            environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
        self.assertEqual(ok.status_code,200)
        self.assertTrue(ok.get_json()["automatic_uploads"])
        self.assertEqual(self.operations,[("join",None)])
        self.operations.clear()
        denied=self.client.post("/api/hive/control/join",json=req,
            headers={"Origin":local},base_url=local,
            environ_overrides={"REMOTE_ADDR":"100.95.3.2"})
        self.assertEqual(denied.status_code,403)
        spoofed=self.client.post("/api/hive/control/join",json=req,
            headers={"Origin":local,"X-Forwarded-For":"100.95.3.2"},
            base_url=local,environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
        self.assertEqual(spoofed.status_code,403)
        self.assertEqual(self.operations,[])

    def test_ui_has_real_controls_without_automatically_sending(self):
        html=(Path(__file__).resolve().parents[1]/"web/templates/hive.html").read_text()
        for name in ("hive-join","hive-disable","hive-revoke","hive-delete-confirm",
                     "allow_hourly_aggregates","acknowledge_pseudonymous_sharing"):
            self.assertIn(name,html)
        self.assertNotIn("hive-owner-key",html)
        self.assertNotIn("X-Ghost-Hive-Owner",html)
        self.assertNotIn("localStorage",html)
        self.assertNotIn("sessionStorage",html)
        self.assertIn("pseudonymous",html.lower())
        self.assertIn("/api/hive/control/",html)
        self.assertNotIn("onclick=",html)


if __name__=="__main__":
    unittest.main()
