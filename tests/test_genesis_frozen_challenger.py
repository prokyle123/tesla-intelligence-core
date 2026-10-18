"""M10 synthetic, offline trial: same-event physics challenger, no production writes."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from genesis.prospective_truth_watch import freeze_watch
from genesis.frozen_challenger import freeze_challenger,challenger_status
from genesis.workspace import create_workspace_app

NOW=1800000000.
DAY=86400

class FrozenChallengerTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory()
  self.addCleanup(t.cleanup)
  self.root=Path(t.name)
  os.chmod(self.root,0o700)
  self.source=self.root/"production.sqlite3"
  self.watch=self.root/"prospective-truth-watch.json"
  self.challenger=self.root/"prospective-challenger.json"
  with closing(sqlite3.connect(self.source)) as con:
   con.executescript("""
   CREATE TABLE telemetry(id INTEGER PRIMARY KEY,car_id TEXT,
      battery_temp_c REAL,outside_temp_c REAL,route TEXT);
   CREATE TABLE prediction_audit(id INTEGER PRIMARY KEY,
      predicted_at REAL,target_ts REAL,resolved_at REAL,
      status TEXT,target_field TEXT,model_name TEXT,generation INTEGER,
      horizon_minutes INTEGER,predicted_value REAL,actual_value REAL,
      source_telemetry_id INTEGER);
   """)
   con.execute("INSERT INTO telemetry VALUES(1,'PRIVATE_CAR',20,10,'SECRET_ROUTE')")
   con.execute("INSERT INTO telemetry VALUES(2,'PRIVATE_CAR',20,NULL,'SECRET_ROUTE')")
   old=[]
   for n in range(200):
    # Every training row was scored at least seven days before the freeze;
    # 3 distinct holdout days, with no future data used for learning.
    training_time=NOW-(10+n%9)*DAY
    holdout_time=NOW-(2+n%3)*DAY
    for horizon in (60,180):
     for moment in (training_time,holdout_time):
      old.append((moment-4000,moment-400,moment,
        "resolved","battery_temp_c",
        f"pack_temp_{horizon}m",13 if horizon==60 else 15,
        horizon,15,16,1))
   con.executemany("""INSERT INTO prediction_audit(
      predicted_at,target_ts,resolved_at,status,target_field,
      model_name,generation,horizon_minutes,predicted_value,actual_value,
      source_telemetry_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",old)
   con.commit()
 def put_future(self,num=150,*,gen=13,src=1,now=NOW,model="pack_temp_60m",
                horizon=60,actual=16,forecast=15):
  with closing(sqlite3.connect(self.source)) as con:
   for i in range(num):
    offset=i%3*DAY
    at=now+120+offset
    con.execute("""INSERT INTO prediction_audit(
      predicted_at,target_ts,resolved_at,status,target_field,
      model_name,generation,horizon_minutes,predicted_value,actual_value,
      source_telemetry_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (at,at+horizon*60,at+horizon*60+40,"resolved","battery_temp_c",
       model,gen,horizon,forecast,actual,src))
   con.commit()
 def test_freeze_then_future_same_event_three_way_comparison(self):
  freeze_watch(self.source,self.watch,now=NOW)
  prior_watch=self.watch.read_bytes()
  self.assertEqual(challenger_status(self.source,self.watch,self.challenger,
                   now=NOW)["status"],"NOT_FROZEN")
  before=hashlib.sha256(self.source.read_bytes()).hexdigest()
  frozen=freeze_challenger(self.source,self.watch,self.challenger,now=NOW)
  self.assertEqual(frozen["status"],"FROZEN_CHALLENGER_RESEARCH_ONLY")
  self.assertEqual(len(frozen["candidates"]),2)
  self.assertEqual(frozen["candidates"][0]["alpha"],0.4)
  self.assertEqual(self.challenger.stat().st_mode&0o777,0o600)
  self.assertEqual(prior_watch,self.watch.read_bytes())
  self.assertEqual(before,hashlib.sha256(self.source.read_bytes()).hexdigest())
  with self.assertRaises(ValueError):
   freeze_challenger(self.source,self.watch,self.challenger,now=NOW)
  now=NOW+5*DAY
  self.put_future()
  self.put_future(num=1,gen=16)
  self.put_future(num=1,src=2)
  report=challenger_status(self.source,self.watch,self.challenger,now=now)
  self.assertEqual(report["status"],"POST_FREEZE_CHALLENGE_AVAILABLE")
  self.assertEqual(report["generation_excluded"],1)
  self.assertEqual(report["incomplete_pairs"],1)
  self.assertEqual(report["matched_pairs"],150)
  row=next(x for x in report["models"] if x["model"]=="pack_temp_60m")
  self.assertEqual(row["samples"],150)
  self.assertEqual(row["evidence_days"],3)
  self.assertEqual(row["production_mae_f"],1.8)
  self.assertEqual(row["persistence_mae_f"],7.2)
  self.assertEqual(row["challenger_mae_f"],0)
  self.assertEqual(row["assessment"],"CHALLENGER_BETTER_ON_FUTURE_SCORES")
  self.assertEqual(row["challenger_advantage_vs_production_f"],1.8)
  self.assertEqual(row["challenger_advantage_vs_persistence_f"],7.2)
  snapshot=self.source.read_bytes()
  challenger_status(self.source,self.watch,self.challenger,now=now)
  self.assertEqual(snapshot,self.source.read_bytes())
  serialized=json.dumps(report)
  for secret in ("PRIVATE_CAR","SECRET_ROUTE","car_id","route",
                 "source_telemetry_id","predicted_at","target_ts"):
   self.assertNotIn(secret,serialized)
  for flag in ("can_promote","automatic_execution","production_changes","network_uploads"):
   self.assertFalse(report[flag])
 def test_cannot_trust_mutated_challenger_or_other_watch(self):
  freeze_watch(self.source,self.watch,now=NOW)
  freeze_challenger(self.source,self.watch,self.challenger,now=NOW)
  raw=self.challenger.read_text()
  self.challenger.write_text(raw.replace('"alpha":0.4','"alpha":0.8'))
  with self.assertRaises(ValueError):
   challenger_status(self.source,self.watch,self.challenger,now=NOW+DAY)
 def test_future_missing_and_temporal_coverage(self):
  freeze_watch(self.source,self.watch,now=NOW)
  freeze_challenger(self.source,self.watch,self.challenger,now=NOW)
  self.put_future(num=140,now=NOW)  # same function schedules three distinct days
  r=challenger_status(self.source,self.watch,self.challenger,now=NOW+5*DAY)
  row=next(x for x in r["models"] if x["model"]=="pack_temp_60m")
  self.assertEqual(row["evidence_days"],3)
  self.assertGreaterEqual(row["samples"],100)
 def test_multivehicle_freeze_fails_closed(self):
  freeze_watch(self.source,self.watch,now=NOW)
  with closing(sqlite3.connect(self.source)) as con:
   con.execute("INSERT INTO telemetry VALUES(3,'OTHER_CAR',20,10,'OTHER')")
   con.commit()
  with self.assertRaises(ValueError):
   freeze_challenger(self.source,self.watch,self.challenger,now=NOW)
  self.assertFalse(self.challenger.exists())
 def test_readonly_endpoint_does_not_initiate_freeze(self):
  app=create_workspace_app(data_dir=self.root)
  app.testing=True
  app.config["GENESIS_SOURCE_DB"]=str(self.source)
  with patch("genesis.api.challenger_status",return_value=
    challenger_status(self.source,self.watch,self.challenger,now=NOW)):
   client=app.test_client()
   response=client.get("/api/genesis/challenger")
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.get_json()["status"],"NOT_FROZEN")
   self.assertEqual(client.post("/api/genesis/challenger").status_code,405)
   self.assertFalse(self.challenger.exists())

if __name__=="__main__":unittest.main()
