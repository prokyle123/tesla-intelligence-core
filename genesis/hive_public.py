"""Public-safe data export for a static Hive dashboard (e.g. GitHub Pages).

Public contributor count starts at ZERO and can show one contributor; model
evaluation statistics require 10 independently enrolled *nodes* per month.
Enrollment cannot establish unique humans or honest data provenance.
No raw records, IDs, locations, model files, credentials or timestamps.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote
from .hive_regions import public_regions, MIN_REGION_MEMBERS

K=10
MONTHS=12

def summary(db:Path, *,now:datetime|None=None)->dict:
    current=now or datetime.now(timezone.utc)
    now_month=current.strftime("%Y-%m")
    y,m=current.year,current.month
    months=[]
    for _ in range(MONTHS):
        months.append(f"{y:04d}-{m:02d}")
        m-=1
        if m==0:y-=1;m=12
    months.reverse()
    path=Path(db).expanduser().resolve()
    uri="file:"+quote(str(path),safe="/")+"?mode=ro"
    with closing(sqlite3.connect(uri,uri=True,timeout=4)) as con:
        con.execute("PRAGMA query_only=ON")
        num=con.execute("""SELECT COUNT(DISTINCT m.participant)
            FROM monthly_research m JOIN participants p
            ON m.participant=p.id WHERE p.enabled=1""").fetchone()[0] or 0
        rows=con.execute("""SELECT m.month,COUNT(DISTINCT m.participant),
                        SUM(m.scored_predictions),SUM(m.total_abs_error_c)
            FROM monthly_research m JOIN participants p
            ON m.participant=p.id WHERE p.enabled=1
            AND m.month>=? AND m.month<=?
            GROUP BY m.month""",(months[0],months[-1])).fetchall()
        approved_regions=public_regions(con,threshold=MIN_REGION_MEMBERS,month=now_month)
    saved={r[0]:r for r in rows}
    timeline=[]
    for month in months:
        r=saved.get(month)
        publish=bool(r and r[1]>=K)
        timeline.append({
            "month":month,
            "label":datetime.strptime(month,"%Y-%m").strftime("%b %Y"),
            "status":"SHARED_GROUP" if publish else "SMALL_GROUP_PRIVATE",
            "reporting_nodes":int(r[1]) if publish else None,
            "predictions_checked":int(r[2]) if publish else None,
            "mean_error_f":round(1.8*r[3]/r[2],2) if publish and r[2] else None,
        })
    latest=next((r for r in reversed(timeline) if r["status"]=="SHARED_GROUP"),None)
    return {
        "schema":"ghost-hive-public-v1",
        "published_at_utc":current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":"SELF_REPORTED_ENROLLED_INSTALLATIONS",
        "network_status":"COORDINATOR_REPORT",
        "reporting_nodes":int(num),
        "verified_unique_people":False,
        "fleet_accuracy_percent":None,
        "predictions_checked":latest["predictions_checked"] if latest else None,
        "mean_error_f":latest["mean_error_f"] if latest else None,
        "monthly":timeline,
        "regions":approved_regions,"countries":None,
        "private_group_threshold":K,
        "model_weights_shared":False,
        "privacy_note":"Member totals count reporting enrollments, not verified humans. Monthly model averages require at least 10 reporting enrollments in the same UTC month. An explicitly opted-in installation may publish its own broad-region marker at one; other small groups remain hidden. No exact location or routes are collected.",
        "federated_models_enabled":False,
    }


def main(argv=None)->int:
    p=argparse.ArgumentParser(description="Export ONLY nonidentifying Hive public cohort JSON")
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args(argv)
    if args.out.expanduser().resolve()==args.db.expanduser().resolve():
        p.error("Cannot export over the private hub database")
    data=summary(args.db)
    out=args.out.expanduser().absolute()
    out.parent.mkdir(parents=True,exist_ok=True)
    import os,tempfile
    fd,tmp=tempfile.mkstemp(prefix=".hive-public-",dir=out.parent)
    try:
        with os.fdopen(fd,"w") as fp:
            json.dump(data,fp,sort_keys=True,indent=2,allow_nan=False)
        os.replace(tmp,out)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print(json.dumps({"exported":True,"public_nodes":data["reporting_nodes"],
                      "qualified_months":sum(x["status"]=="SHARED_GROUP" for x in data["monthly"]),
                      "contains_individual_members":False},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
