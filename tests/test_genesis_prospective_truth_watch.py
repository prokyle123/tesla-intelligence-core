"""M8: future evidence must be unavailable until a real manual freeze."""
from contextlib import closing
from pathlib import Path
import hashlib,json,os,sqlite3,tempfile,unittest
from unittest.mock import patch
from genesis.prospective_truth_watch import freeze_watch,check_watch
from genesis.workspace import create_workspace_app
NOW=1800000000.
DAY=86400

class ProspectiveTruthWatchTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  self.home=Path(t.name);self.state=self.home/"watch.json"
  self.db=self.home/"source.sqlite3"
  with closing(sqlite3.connect(self.db)) as c:
   c.executescript("""
    CREATE TABLE telemetry(id INTEGER PRIMARY KEY,car_id TEXT,battery_temp_c REAL,private_route TEXT);
    CREATE TABLE prediction_audit(id INTEGER PRIMARY KEY,predicted_at REAL,target_ts REAL,
      resolved_at REAL,status TEXT,target_field TEXT,model_name TEXT,
      generation INTEGER,horizon_minutes INTEGER,predicted_value REAL,
      actual_value REAL,source_telemetry_id INTEGER);
   """)
   c.execute("INSERT INTO telemetry VALUES(1,'PRIVATE_CAR',20,'PRIVATE_ROUTE')")
   c.execute("""INSERT INTO prediction_audit VALUES(1,?,?,?,?,?,?,?,?,?,?,?)""",
     (NOW-2*DAY,NOW-DAY,NOW,"resolved","battery_temp_c",
      "pack_temp_60m",13,60,24.,20.,1))
   c.commit()
  os.chmod(self.home,0o700)
 def put(self,id,created,resolved,gen=13,pred=24.,actual=20.,source=1):
  with closing(sqlite3.connect(self.db)) as c:
   c.execute("INSERT INTO prediction_audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
     (id,created,created+3600,resolved,"resolved","battery_temp_c",
      "pack_temp_60m",gen,60,pred,actual,source))
   c.commit()
 def test_future_only_and_immutable_watch(self):
  self.assertEqual(check_watch(self.db,self.state,now=NOW)["status"],"NOT_FROZEN")
  freeze=freeze_watch(self.db,self.state,now=NOW)
  self.assertEqual(freeze["status"],"FROZEN_AWAITING_NEW_SCORES")
  self.assertEqual(os.stat(self.state).st_mode&0o777,0o600)
  with self.assertRaises(ValueError):freeze_watch(self.db,self.state,now=NOW)
  # Resolved after freeze, but original forecast predates freeze -> excluded.
  self.put(2,NOW-100,NOW+7200)
  # New ID but backdated sensor forecast -> excluded.
  self.put(3,NOW-10000,NOW+7200)
  for i in range(4,124):
   self.put(i,NOW+30,NOW+7200,pred=24.,actual=20.)
  # Same new period, unapproved next model generation -> suppressed.
  self.put(124,NOW+30,NOW+7200,gen=14)
  # Missing source packs cannot fake a successful paired baseline.
  self.put(125,NOW+30,NOW+7200,source=999)
  report=check_watch(self.db,self.state,now=NOW+10800)
  self.assertEqual(report["status"],"POST_FREEZE_EVIDENCE_AVAILABLE")
  self.assertEqual(report["eligible_pairs"],120)
  self.assertEqual(report["incomplete_pairs"],1)
  self.assertEqual(report["new_generation_pairs"],1)
  row=next(r for r in report["models"] if r["model"]=="pack_temp_60m")
  self.assertEqual(row["model_mae_f"],7.2)
  self.assertEqual(row["persistence_mae_f"],0)
  self.assertEqual(row["model_advantage_f"],-7.2)
  self.assertEqual(row["evidence_days"],1)
  self.assertEqual(row["assessment"],"INSUFFICIENT_TEMPORAL_COVERAGE")
  after_inserts=hashlib.sha256(self.db.read_bytes()).hexdigest()
  check_watch(self.db,self.state,now=NOW+10800)
  self.assertEqual(after_inserts,hashlib.sha256(self.db.read_bytes()).hexdigest())
  dump=json.dumps(report)
  for bad in ("PRIVATE_CAR","PRIVATE_ROUTE","source_telemetry_id","predicted_at","resolved_at"):
   self.assertNotIn(bad,dump)
  for key in ("network_uploads","production_changes","can_promote","automatic_execution"):
   self.assertFalse(report[key])
 def test_three_distinct_future_days_allow_comparison(self):
  freeze_watch(self.db,self.state,now=NOW)
  for i in range(120):
   offset=(i%3)*DAY
   self.put(i+2,NOW+30+offset,NOW+7200+offset,pred=24.,actual=20.)
  result=check_watch(self.db,self.state,now=NOW+4*DAY)
  self.assertEqual(result["eligible_pairs"],120)
  self.assertEqual(result["min_evidence_days"],3)
  row=result["models"][0]
  self.assertEqual(row["evidence_days"],3)
  self.assertEqual(row["assessment"],"PERSISTENCE_BETTER_REVIEW")
  self.assertEqual(row["model_advantage_f"],-7.2)

 def test_zero_future_scores_are_complete_and_private(self):
  freeze_watch(self.db,self.state,now=NOW)
  report=check_watch(self.db,self.state,now=NOW+2)
  self.assertEqual(report["status"],"AWAITING_FUTURE_EVIDENCE")
  self.assertEqual(report["models"][0]["samples"],0)
  self.assertEqual(report["models"][0]["evidence_days"],0)
  self.assertIsNone(report["models"][0]["model_advantage_f"])
 def test_same_source_and_multicar_isolation(self):
  freeze_watch(self.db,self.state,now=NOW)
  self.assertRaises(ValueError,check_watch,self.home/"missing.sqlite3",self.state)
  with closing(sqlite3.connect(self.db)) as c:
   c.execute("INSERT INTO telemetry VALUES(2,'DIFFERENT_CAR',10,'OTHER')");c.commit()
  self.assertRaises(ValueError,check_watch,self.db,self.state,now=NOW+5)
 def test_get_only_and_no_implicit_freeze(self):
  app=create_workspace_app(data_dir=self.home);app.testing=True
  app.config["GENESIS_SOURCE_DB"]=str(self.db)
  with patch("genesis.api.check_watch",return_value=check_watch(self.db,self.state,now=NOW)):
   c=app.test_client();r=c.get("/api/genesis/prospective-watch")
   self.assertEqual(r.status_code,200)
   self.assertEqual(r.get_json()["status"],"NOT_FROZEN")
   self.assertEqual(c.post("/api/genesis/prospective-watch").status_code,405)
  self.assertFalse(self.state.exists())
if __name__=="__main__":unittest.main()
