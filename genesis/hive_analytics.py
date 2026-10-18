"""Privacy-gated Hive Analytics query.

Only monthly group metrics for >=25 enabled registered nodes are released.
This is NOT anonymous or differentially private aggregation: operators
can inspect per-node aggregate records in the private server database.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from .hive_protocol import MIN_COHORT,METRIC

MONTHS=6
ORIGINS=frozenset(("synthetic","qualified_post_freeze"))


def _recent_months(now: datetime|None=None)->list[str]:
    current=now or datetime.now(timezone.utc)
    year,month=current.year,current.month
    periods=[]
    for _ in range(MONTHS):
        periods.append(f"{year:04d}-{month:02d}")
        month-=1
        if month==0:
            month=12
            year-=1
    return periods[::-1]


def cohort_dashboard(db: Path,*,origin: str="synthetic",
                     now: datetime|None=None)->dict:
    if origin not in ORIGINS:
        raise ValueError("Unsupported cohort type")
    months=_recent_months(now)
    data={}
    # Query aggregates in SQL. Never put participant ids or individual
    # contributions in the output or in user-facing templates.
    with closing(sqlite3.connect(db)) as con:
        rows=con.execute("""
            SELECT period,COUNT(DISTINCT participant),
                   COALESCE(SUM(episodes),0),
                   COALESCE(SUM(mae_c*episodes),0)
            FROM contributions
            WHERE origin=? AND metric=? AND period>=? AND period<=?
              AND participant IN (SELECT id FROM participants WHERE enabled=1)
            GROUP BY period
            """,(origin,METRIC,months[0],months[-1])).fetchall()
        for period,count,episodes,weighted in rows:
            if count>=MIN_COHORT and episodes>0:
                data[period]={"participants":count,
                              "episodes":episodes,
                              "mean_error_f":round(1.8*weighted/episodes,2)}
        # Retention is shown only when both consecutive cohorts satisfy
        # the exact same release threshold, not for sparse months.
        returning={}
        for index in range(1,len(months)):
            period,previous=months[index],months[index-1]
            if period not in data or previous not in data:
                continue
            returning[period]=con.execute("""
                SELECT COUNT(DISTINCT cur.participant)
                FROM contributions cur JOIN contributions prev
                  ON cur.participant=prev.participant
                JOIN participants p ON p.id=cur.participant AND p.enabled=1
                WHERE cur.period=? AND prev.period=?
                  AND cur.metric=? AND prev.metric=?
                  AND cur.origin=? AND prev.origin=?
                """,(period,previous,METRIC,METRIC,origin,origin)).fetchone()[0]

    timeline=[]
    for period in months:
        safe=data.get(period)
        entry={"period":period,"label":datetime.strptime(period,"%Y-%m").strftime("%b %Y"),
               "status":"READY" if safe else "WITHHELD",
               "contributors":safe["participants"] if safe else None,
               "predictions":safe["episodes"] if safe else None,
               "average_error_f":safe["mean_error_f"] if safe else None,
               "returning_contributors":returning.get(period)}
        timeline.append(entry)
    published=[entry for entry in timeline if entry["status"]=="READY"]
    latest=published[-1] if published else None
    total_predictions=sum(x["predictions"] for x in published)
    return {
        "status":"COHORT_AVAILABLE" if latest else "BUILDING_PRIVATE_COHORT",
        "origin":origin,"demo":False,"cohort_threshold":MIN_COHORT,
        "months":timeline,
        "summary":{
            "latest_period":latest["period"] if latest else None,
            "contributors":latest["contributors"] if latest else None,
            "predictions_evaluated":total_predictions if published else None,
            "average_error_f":latest["average_error_f"] if latest else None,
            "returning_contributors":latest["returning_contributors"] if latest else None,
            "months_available":len(published),
        },
        "privacy":{
            "displays_individual_members":False,
            "individual_uploads_visible_to_server_operator":True,
            "anonymous_federated_learning":False,
            "real_car_data_enabled":False,
            "minimum_nodes_for_group_metrics":MIN_COHORT,
        },
        "explanation":(
            "Group statistics appear only when at least 25 distinct enabled "
            "enrolled nodes contribute within a month. Registration does not "
            "prove 25 different people. Prediction error is a temperature "
            "difference expressed in °F, not actual battery temperature."
        ),
    }


def synthetic_demo(*,now: datetime|None=None)->dict:
    """Clearly marked, entirely fictional UI example, never touches Hive DB."""
    months=_recent_months(now)
    contributors=(26,28,31,34,37,41)
    episodes=(675,742,835,906,1008,1150)
    errors=(2.9,2.7,2.6,2.42,2.35,2.18)
    items=[]
    for i,period in enumerate(months):
        items.append({
            "period":period,
            "label":datetime.strptime(period,"%Y-%m").strftime("%b %Y"),
            "status":"READY","contributors":contributors[i],
            "predictions":episodes[i],"average_error_f":errors[i],
            "returning_contributors":None if i==0 else int(contributors[i-1]*.7),
        })
    return {
        "status":"SYNTHETIC_DEMO_ONLY","origin":"synthetic","demo":True,
        "cohort_threshold":MIN_COHORT,"months":items,
        "summary":{"latest_period":months[-1],"contributors":contributors[-1],
                   "predictions_evaluated":sum(episodes),
                   "average_error_f":errors[-1],
                   "returning_contributors":items[-1]["returning_contributors"],
                   "months_available":MONTHS},
        "privacy":{"displays_individual_members":False,
                   "individual_uploads_visible_to_server_operator":True,
                   "anonymous_federated_learning":False,
                   "real_car_data_enabled":False,
                   "minimum_nodes_for_group_metrics":MIN_COHORT},
        "explanation":"ALL figures on this demo are fictional. No vehicles or registered participants were used.",
    }
