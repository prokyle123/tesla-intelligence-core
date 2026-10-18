"""First-report publication requires distinct token-backed consent."""
from pathlib import Path
from datetime import datetime,timezone
import sqlite3
import tempfile
import unittest
from contextlib import closing

from genesis.hive_server import create_app,enroll,initialize
from genesis.hive_public import summary
from scripts.hive_public_snapshot_guard import check

class PublicFirstMonthlyTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db=Path(folder.name)/"hive.sqlite3"
        self.app=create_app(self.db)
        self.app.testing=True
        self.client=self.app.test_client()
        self.first=enroll(self.db)

    def request(self,token,path,method="PUT",body=None):
        return self.client.open(path,method=method,
          headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
          json=body)

    def send(self,token,n,absolute):
        packet={"schema":"ghost-hive-monthly-v1",
            "metric":"ghost-battery-temp-forecast-mae-v1",
            "month":"2026-10","scored_predictions":n,
            "total_abs_error_c":absolute,"source":"ghost_prediction_audit"}
        response=self.request(token,"/v1/monthly-research","POST",packet)
        self.assertEqual(response.status_code,202,response.get_json())

    def feed(self):
        return check(summary(self.db,now=datetime(2026,10,18,21,tzinfo=timezone.utc)))

    def test_one_member_is_visible_only_after_distinct_public_monthly_consent(self):
        self.send(self.first,2,3.)
        self.assertEqual(self.feed()["reporting_nodes"],1)
        self.assertIsNone(self.feed()["predictions_checked"])
        self.assertEqual(self.feed()["monthly"][-1]["status"],"SMALL_GROUP_PRIVATE")
        bad=self.request(self.first,"/v1/monthly-publication",
            body={"schema":"ghost-hive-monthly-public-v1"})
        self.assertEqual(bad.status_code,400)
        yes=self.request(self.first,"/v1/monthly-publication",
            body={"schema":"ghost-hive-monthly-public-v1",
                  "acknowledge_public_from_one":True})
        self.assertEqual(yes.status_code,202)
        public=self.feed()
        self.assertEqual(public["predictions_checked"],2)
        self.assertAlmostEqual(public["mean_error_f"],2.7)
        self.assertEqual(public["monthly"][-1]["status"],"EXPLICIT_PUBLIC_OPT_IN")
        self.assertEqual(public["monthly"][-1]["reporting_nodes"],1)
        hidden=self.request(self.first,"/v1/monthly-publication","DELETE")
        self.assertEqual(hidden.status_code,200)
        self.assertIsNone(self.feed()["predictions_checked"])

    def test_nonconsenting_peer_cannot_leak_into_one_public_members_metrics(self):
        second=enroll(self.db)
        self.send(self.first,1,1)
        self.send(second,50,999.)
        consent={"schema":"ghost-hive-monthly-public-v1",
                 "acknowledge_public_from_one":True}
        self.assertEqual(self.request(self.first,"/v1/monthly-publication",body=consent).status_code,202)
        published=self.feed()
        self.assertEqual(published["reporting_nodes"],2)
        self.assertEqual(published["monthly"][-1]["reporting_nodes"],1)
        self.assertEqual(published["predictions_checked"],1)
        self.assertEqual(published["mean_error_f"],1.8)

    def test_old_db_migrates_privately_by_default(self):
        self.send(self.first,1,1.)
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("ALTER TABLE participants RENAME TO previous_members")
            con.execute("""CREATE TABLE participants(
                id INTEGER PRIMARY KEY,secret_hash TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)""")
            con.execute("""INSERT INTO participants(id,secret_hash,created_at,enabled)
                            SELECT id,secret_hash,created_at,enabled FROM previous_members""")
            con.execute("DROP TABLE previous_members")
            con.commit()
        self.assertIsNone(self.feed()["predictions_checked"])
        initialize(self.db)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT public_monthly FROM participants").fetchone()[0],0)
        self.assertIsNone(self.feed()["predictions_checked"])

    def test_page_supports_first_member_consent_and_monthly_results(self):
        html=(Path(__file__).resolve().parents[1]/"web/templates/hive.html").read_text()
        public=(Path(__file__).resolve().parents[1]/"docs/hive/index.html").read_text()
        for key in ("hive-monthly-publish","hive-monthly-hide",
                    "hive-monthly-singleton-ack","EXPLICIT_PUBLIC_OPT_IN"):
            self.assertIn(key,html)
        self.assertIn("EXPLICIT_PUBLIC_OPT_IN",public)
        self.assertIn("months.some(m=>m.status",public)

if __name__=="__main__":
    unittest.main()
