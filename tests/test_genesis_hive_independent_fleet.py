"""M12 independent Hive Fleet Intel: no self-inclusion, no private peer leak."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from genesis.hive_server import create_app,enroll
from genesis.hive_peer_comparison import compare
from genesis.hive_monthly import SCHEMA, METRIC

MONTH="2026-10"


class IndependentComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"hive.sqlite3"
        self.app=create_app(self.db)
        self.app.testing=True
        self.client=self.app.test_client()
        self.owner=enroll(self.db)
        self.owner_id=1
        self.now=datetime(2026,10,18,tzinfo=timezone.utc)

    def call(self,token,path,method="GET",body=None):
        return self.client.open(path,method=method,json=body,
            headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})

    def upload(self,token,n=25,total_c=25.,month=MONTH):
        packet={"schema":SCHEMA,"metric":METRIC,"month":month,
                "scored_predictions":n,"total_abs_error_c":total_c,
                "source":"ghost_prediction_audit"}
        res=self.call(token,"/v1/monthly-research","POST",packet)
        self.assertEqual(res.status_code,202,res.get_json())

    def publish(self,token):
        body={"schema":"ghost-hive-monthly-public-v1",
              "acknowledge_public_from_one":True}
        with patch("genesis.hive_server.time.gmtime",
                   return_value=__import__("time").strptime("2026-10-18","%Y-%m-%d")):
            result=self.call(token,"/v1/monthly-publication","PUT",body)
        self.assertEqual(result.status_code,202,result.get_json())

    def score(self):
        return compare(self.db,self.owner_id,now=self.now)

    def test_bearer_required_even_on_local_private_coordinator(self):
        self.assertEqual(self.client.get("/v1/member-comparison").status_code,401)
        self.assertEqual(self.call("bad","/v1/member-comparison").status_code,401)
        response=self.call(self.owner,"/v1/member-comparison")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["status"],"AWAITING_LOCAL_MONTHLY_REPORT")
        self.assertTrue(response.get_json()["self_excluded_from_peers"])

    def test_one_installation_does_not_compare_against_itself(self):
        self.upload(self.owner,n=25,total_c=25.)
        result=self.score()
        self.assertEqual(result["status"],"AWAITING_PUBLISHABLE_PEERS")
        row=result["months"][-1]
        self.assertEqual(row["self_predictions"],25)
        self.assertEqual(row["self_mae_f"],1.8)
        self.assertIsNone(row["peer_mae_f"])
        self.assertIsNone(row["peer_installations"])
        self.assertIsNone(row["self_advantage_f"])
        self.assertNotIn("participant",str(row))

    def test_one_nonpublic_peer_remains_withheld(self):
        self.upload(self.owner,n=25,total_c=25.)
        other=enroll(self.db)
        self.upload(other,n=50,total_c=100.)
        row=self.score()["months"][-1]
        self.assertEqual(row["peer_visibility"],"NO_PUBLISHABLE_PEERS")
        self.assertIsNone(row["peer_installations"])
        self.assertIsNone(row["peer_mae_f"])
        # Making OWNER public still does not make somebody else's data public.
        self.publish(self.owner)
        self.assertIsNone(self.score()["months"][-1]["peer_mae_f"])

    def test_explicit_public_peer_shows_true_other_only_monthly_mae(self):
        self.upload(self.owner,n=25,total_c=25.)  # 1.80 F
        other=enroll(self.db)
        self.upload(other,n=50,total_c=150.)  # 5.40 F
        self.publish(other)
        result=self.score()
        row=result["months"][-1]
        self.assertEqual(result["status"],"COMPARISON_AVAILABLE")
        self.assertEqual(row["peer_installations"],1)
        self.assertEqual(row["peer_predictions"],50)
        self.assertEqual(row["peer_mae_f"],5.4)
        self.assertEqual(row["self_mae_f"],1.8)
        self.assertEqual(row["self_advantage_f"],3.6)
        self.assertEqual(row["peer_visibility"],"EXPLICIT_PUBLIC_PEERS")
        # A third nonconsenting peer is NOT added to this one-peer aggregate.
        hidden=enroll(self.db)
        self.upload(hidden,n=25,total_c=500.)
        r=self.score()["months"][-1]
        self.assertEqual(r["peer_installations"],1)
        self.assertEqual(r["peer_predictions"],50)
        self.assertEqual(r["peer_mae_f"],5.4)

    def test_private_ten_OTHER_installation_cohort_is_qualifying(self):
        self.upload(self.owner,n=25,total_c=25.)
        for _ in range(9):
            token=enroll(self.db)
            self.upload(token,n=25,total_c=100.)
        nine=self.score()["months"][-1]
        self.assertIsNone(nine["peer_mae_f"])
        token=enroll(self.db)
        self.upload(token,n=25,total_c=100.)
        ten=self.score()["months"][-1]
        self.assertEqual(ten["peer_visibility"],"QUALIFIED_PEER_COHORT")
        self.assertEqual(ten["peer_installations"],10)
        self.assertEqual(ten["peer_predictions"],250)
        self.assertEqual(ten["peer_mae_f"],7.2)

    def test_revoked_member_disappears_and_no_old_month_auto_public(self):
        self.upload(self.owner,n=25,total_c=25.)
        second=enroll(self.db)
        self.upload(second,n=25,total_c=125.,month="2026-09")
        self.upload(second,n=25,total_c=100.)
        self.publish(second)
        earlier=self.score()["months"][-2]
        self.assertIsNone(earlier["peer_mae_f"])
        self.assertEqual(self.score()["months"][-1]["peer_mae_f"],7.2)
        deleted=self.call(second,"/v1/enrollment","DELETE")
        self.assertEqual(deleted.status_code,200)
        self.assertIsNone(self.score()["months"][-1]["peer_mae_f"])

    def test_client_and_private_ui_do_not_emit_owner_token(self):
        root=Path(__file__).resolve().parents[1]
        frontend=(root/"web/templates/hive.html").read_text()
        client=(root/"genesis/hive_peer_client.py").read_text()
        local=(root/"ghost_tesla_ai/hive_local.py").read_text()
        for needle in ('id="peer-title"','id="peer-history"',
                       'renderPeer(await response.json())',
                       '"/api/hive/peer-comparison"',
                       'Your submitted monthly MAE'):
            self.assertIn(needle,frontend)
        self.assertIn('"/v1/member-comparison"',client)
        self.assertIn("member._read_private",client)
        self.assertIn('"/api/hive/peer-comparison"',local)
        self.assertNotIn("member_token",frontend)
        self.assertNotIn('"/api/hive/control/peer-',frontend)


if __name__=="__main__":
    unittest.main()
