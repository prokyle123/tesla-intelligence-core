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
            action.assert_called_once_with("disable",month=None)
            repeated=self.request(headers)
            self.assertEqual(repeated.status_code,403)

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
