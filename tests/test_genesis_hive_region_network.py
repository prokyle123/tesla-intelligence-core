"""End-to-end broad-region privacy: separate opt-in; no individual location."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import tempfile
import unittest
from genesis.hive_server import create_app,enroll
from genesis.hive_public import summary
from genesis.hive_regions import REGIONS,REGION_SCHEMA
from scripts.hive_public_snapshot_guard import check

class HiveBroadRegionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/"hive.sqlite3"
        self.app=create_app(self.db)
        self.app.testing=True
        self.client=self.app.test_client()
        self.member_token=enroll(self.db)

    def snapshot(self):
        return summary(self.db,now=datetime(2026,10,18,12,tzinfo=timezone.utc))

    def submit(self,token,*,path,method,data=None):
        return self.client.open(path,method=method,
          headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
          json=data)

    def publish(self,token):
        packet={"schema":"ghost-hive-monthly-v1",
                "metric":"ghost-battery-temp-forecast-mae-v1",
                "month":"2026-10","scored_predictions":25,
                "total_abs_error_c":31.5,"source":"ghost_prediction_audit"}
        answer=self.submit(token,path="/v1/monthly-research",method="POST",data=packet)
        self.assertEqual(answer.status_code,202)

    def pick(self,token,code="NORTH_AMERICA_EAST"):
        return self.submit(token,path="/v1/region",method="PUT",
                           data={"schema":REGION_SCHEMA,"region_code":code})

    def test_one_consented_reporter_never_generates_public_dot(self):
        self.publish(self.member_token)
        self.assertEqual(self.pick(self.member_token).status_code,202)
        snapshot=check(self.snapshot())
        self.assertEqual(snapshot["reporting_nodes"],1)
        self.assertEqual(snapshot["regions"],[])
        self.assertIsNone(snapshot["countries"])
        # Attempts to sneak exact location/coordinates into region protocol fail.
        bad=self.submit(self.member_token,path="/v1/region",method="PUT",
          data={"schema":REGION_SCHEMA,"region_code":"NORTH_AMERICA_EAST",
                "latitude":41.8,"longitude":-87.6})
        self.assertEqual(bad.status_code,400)
        self.assertEqual(check(self.snapshot())["regions"],[])

    def test_ten_consented_members_publish_only_approved_centroid(self):
        self.publish(self.member_token)
        self.assertEqual(self.pick(self.member_token).status_code,202)
        tokens=[self.member_token]
        for _ in range(9):
            key=enroll(self.db);tokens.append(key)
            self.publish(key)
            self.assertEqual(self.pick(key).status_code,202)
        public=check(self.snapshot())
        self.assertEqual(public["reporting_nodes"],10)
        self.assertEqual(len(public["regions"]),1)
        region=public["regions"][0]
        self.assertEqual(region,{"code":"NORTH_AMERICA_EAST",
            "label":"Eastern North America","x":180,"y":110,"reporting_nodes":10})
        self.assertEqual(self.submit(tokens[0],path="/v1/region",method="DELETE").status_code,200)
        self.assertEqual(check(self.snapshot())["regions"],[])
        # Only active reporting owners count. Revocation must erase location consent.
        self.assertEqual(self.submit(tokens[1],path="/v1/enrollment",method="DELETE").status_code,200)
        self.assertEqual(check(self.snapshot())["reporting_nodes"],9)

    def test_region_requires_registered_client_and_schema(self):
        anon=self.client.put("/v1/region",json={"schema":REGION_SCHEMA,"region_code":"EUROPE"})
        self.assertEqual(anon.status_code,401)
        other=self.pick(self.member_token,code="EXACT_HOME")
        self.assertEqual(other.status_code,400)
        self.assertEqual(check(self.snapshot())["regions"],[])

if __name__=="__main__":unittest.main()
