"""Owner-management security: PIN gateway signs, raw LAN headers cannot."""
from __future__ import annotations
from contextlib import closing
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from ghost_tesla_ai.hive_local import bp
from ghost_tesla_ai import funnel_gateway, hive_owner_proof as proof

ORIGIN="https://ghost.example"
BODY=b'{"confirmation":"DELETE"}'

class OwnerGatewayTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.pin=self.root/"pin.json"
        self.pin.write_text(json.dumps({
            "session_secret":base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        }))
        self.pin.chmod(0o600)
        self.patcher=patch.object(proof,"OWNER_PIN_FILE",self.pin)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.app=Flask("hive-owner-proof-test")
        self.app.register_blueprint(bp)
        self.app.testing=True
        self.client=self.app.test_client()

    def request(self,headers=None):
        h={"Origin":ORIGIN,"Content-Type":"application/json"}
        h.update(headers or {})
        return self.client.post("/api/hive/control/disable",
                                data=b"{}",headers=h)

    def test_gateway_proof_authenticated_once_only(self):
        headers=proof.sign("POST","/api/hive/control/disable",ORIGIN,b"{}",now=1800000000)
        with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=1800000000), \
             patch("ghost_tesla_ai.hive_local._run_hive_action",
                   return_value={"mode":"OFF"}) as action, \
             patch("ghost_tesla_ai.hive_local._private_consent",
                   return_value={"region_code":None}):
            result=self.request(headers)
            self.assertEqual(result.status_code,200,result.get_json())
            action.assert_called_once_with("disable",month=None,region_code=None)
            repeated=self.request(headers)
            self.assertEqual(repeated.status_code,403)

    def test_region_update_requires_new_explicit_owner_consent(self):
        when=1800000000
        body=json.dumps({"region_code":"NORTH_AMERICA_EAST",
                         "acknowledge_optional_region":True}).encode()
        path="/api/hive/control/region-set"
        with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=when), \
             patch("ghost_tesla_ai.hive_local._private_consent",
                   return_value={"mode":"OPTED_IN","hourly_enabled":True}), \
             patch("ghost_tesla_ai.hive_local._run_hive_action",
                   return_value={"regional_sharing":"OPTED_IN","region_code":"NORTH_AMERICA_EAST"}) as send:
            signed=proof.sign("POST",path,ORIGIN,body,now=when)
            response=self.client.post(path,data=body,
                headers={"Origin":ORIGIN,"Content-Type":"application/json",**signed})
            self.assertEqual(response.status_code,200,response.get_json())
            send.assert_called_once_with("region-set",month=None,region_code="NORTH_AMERICA_EAST")
            rejected=self.client.post(path,
                data=json.dumps({"region_code":"NORTH_AMERICA_EAST"}).encode(),
                headers={"Origin":ORIGIN,"Content-Type":"application/json",
                         **proof.sign("POST",path,ORIGIN,
                                     json.dumps({"region_code":"NORTH_AMERICA_EAST"}).encode(),now=when)})
            self.assertEqual(rejected.status_code,400)
            self.assertEqual(rejected.get_json()["error"],"EXPLICIT_REGION_CONSENT_REQUIRED")
            send.assert_called_once()

    def test_region_clear_uses_authenticated_existing_revocation(self):
        now=1800000000
        path="/api/hive/control/region-clear"
        body=b"{}"
        with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=now), \
             patch("ghost_tesla_ai.hive_local._run_hive_action",
                   return_value={"regional_sharing":"OFF"}) as send:
            headers=proof.sign("POST",path,ORIGIN,body,now=now)
            response=self.client.post(path,data=body,
                headers={"Origin":ORIGIN,"Content-Type":"application/json",**headers})
            self.assertEqual(response.status_code,200,response.get_json())
            send.assert_called_once_with("region-clear",month=None,region_code=None)

    def test_singleton_publication_requires_separate_active_owner_authorization(self):
        timepoint=1800000000
        path="/api/hive/control/region-publish"
        body=json.dumps({"acknowledge_public_singleton":True}).encode()
        with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=timepoint), \
             patch("ghost_tesla_ai.hive_local._private_consent",
                   return_value={"mode":"OPTED_IN","hourly_enabled":True,
                                 "region_code":"NORTH_AMERICA_EAST"}), \
             patch("ghost_tesla_ai.hive_local._run_hive_action",
                   return_value={"public_listing":True}) as send:
            headers={"Origin":ORIGIN,"Content-Type":"application/json",
                     **proof.sign("POST",path,ORIGIN,body,now=timepoint)}
            result=self.client.post(path,data=body,headers=headers)
            self.assertEqual(result.status_code,200,result.get_json())
            self.assertEqual(result.get_json()["public_listing"],True)
            send.assert_called_once_with("region-publish",month=None,region_code=None)
            missing=b"{}"
            invalid=self.client.post(path,data=missing,
                headers={"Origin":ORIGIN,"Content-Type":"application/json",
                         **proof.sign("POST",path,ORIGIN,missing,now=timepoint)})
            self.assertEqual(invalid.status_code,400)
            self.assertEqual(invalid.get_json()["error"],
                             "EXPLICIT_SINGLE_REPORTER_PUBLIC_CONSENT_REQUIRED")
            send.assert_called_once()

    def test_proof_binds_body_origin_path_and_time(self):
        h=proof.sign("POST","/api/hive/control/disable",ORIGIN,b"{}",now=1800000000)
        with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=1800000000):
            self.assertFalse(proof.verify("POST","/api/hive/control/join",ORIGIN,
                b"{}",h,peer="127.0.0.1",now=1800000000))
            self.assertFalse(proof.verify("POST","/api/hive/control/disable",
                "https://evil.example",b"{}",h,peer="127.0.0.1",now=1800000000))
            self.assertFalse(proof.verify("POST","/api/hive/control/disable",
                ORIGIN,b'{"foo":1}',h,peer="127.0.0.1",now=1800000000))
            self.assertFalse(proof.verify("POST","/api/hive/control/disable",
                ORIGIN,b"{}",h,peer="192.168.1.8",now=1800000000))
            self.assertFalse(proof.verify("POST","/api/hive/control/disable",
                ORIGIN,b"{}",h,peer="127.0.0.1",now=1800000040))
            self.assertTrue(proof.verify("POST","/api/hive/control/disable",
                ORIGIN,b"{}",h,peer="127.0.0.1",now=1800000000))

    def test_proxied_strings_and_untrusted_headers_never_authorize(self):
        response=self.request({"X-GHOST-Funnel-Authenticated":"1"})
        self.assertEqual(response.status_code,403)
        response=self.request({"X-Ghost-Owner-Signature":"0"*64})
        self.assertEqual(response.status_code,403)
        self.assertFalse(proof.allowed_browser_origin("http://ghost.example","ghost.example"))
        self.assertFalse(proof.allowed_browser_origin("https://evil.example","ghost.example"))
        self.assertTrue(proof.allowed_browser_origin(ORIGIN,"ghost.example"))
        self.pin.chmod(0o644)
        self.assertIsNone(proof._key())

    def test_gateway_emits_signed_action_only_for_authenticated_https_origin(self):
        class MockResponse:
            status=200
            def read(self):return b'{"mode":"OFF"}'
            def getheaders(self):return [("content-type","application/json")]
        class MockConnection:
            def __init__(self,*args,**kwargs):self.last=None
            def request(self,method,target,body=None,headers=None):
                self.last=(method,target,body,headers)
                emitted.append(self.last)
            def getresponse(self):return MockResponse()
            def close(self):pass
        emitted=[]
        gateway=funnel_gateway.app
        gateway.testing=True
        with patch.object(funnel_gateway,"_load_auth",return_value={"valid":"yes"}), \
             patch.object(funnel_gateway,"_session_ok",return_value=True), \
             patch.object(funnel_gateway.http.client,"HTTPConnection",MockConnection):
            client=gateway.test_client()
            ok=client.post("/api/hive/control/disable",
                    base_url=ORIGIN,data=b"{}",
                    headers={"Origin":ORIGIN,"Content-Type":"application/json",
                             "X-Ghost-Owner-Signature":"injected"})
            self.assertEqual(ok.status_code,200)
            sent=emitted[-1][3]
            self.assertNotEqual(sent["X-Ghost-Owner-Signature"],"injected")
            with patch("ghost_tesla_ai.hive_owner_proof.time.time",return_value=float(sent["X-Ghost-Owner-Timestamp"])):
                self.assertTrue(proof.verify("POST","/api/hive/control/disable",
                    ORIGIN,b"{}",sent,peer="127.0.0.1",
                    now=float(sent["X-Ghost-Owner-Timestamp"])))
            blocked=client.post("/api/hive/control/disable",
                    base_url=ORIGIN,data=b"{}",
                    headers={"Origin":"https://evil.example",
                             "Content-Type":"application/json"})
            self.assertEqual(blocked.status_code,403)
if __name__=="__main__":unittest.main()
