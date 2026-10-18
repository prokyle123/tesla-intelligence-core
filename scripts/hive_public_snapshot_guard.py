"""Fail-closed JSON whitelist for public Hive snapshot publication."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

FIELDS={"schema","published_at_utc","source","network_status","reporting_nodes",
"verified_unique_people","fleet_accuracy_percent","predictions_checked","mean_error_f",
"monthly","regions","countries","private_group_threshold","model_weights_shared",
"privacy_note","federated_models_enabled"}
ROW={"month","label","status","reporting_nodes","predictions_checked","mean_error_f"}
# Fixed approximate geographic macros; never accept free-form location coordinates.
PUBLIC_REGION_CENTERS={
    "NORTH_AMERICA_WEST":("Western North America",128,111),
    "NORTH_AMERICA_EAST":("Eastern North America",180,110),
    "SOUTH_AMERICA":("South America",166,235),
    "EUROPE":("Europe",371,99),
    "AFRICA":("Africa",397,189),
    "ASIA":("Asia",520,118),
    "OCEANIA":("Oceania",653,260),
}
REGION_ROW={"code","label","x","y","reporting_nodes"}
SINGLE_PUBLIC_REGION_ROW=REGION_ROW|{"visibility"}


def check(d):
    def integer(x,low=0):
        if type(x) is not int or not low<=x<=1000000000000:raise ValueError("Unsafe public count")
    def measure(x):
        if type(x) not in (float,int) or not math.isfinite(x) or not 0<=x<=100:
            raise ValueError("Unsafe public error")
    if not isinstance(d,dict) or set(d)!=FIELDS:raise ValueError("Unapproved top-level fields")
    if d["schema"]!="ghost-hive-public-v1" or d["private_group_threshold"]!=10:
        raise ValueError("Unsupported schema/privacy gate")
    if d["source"] not in ("NO_EXPORT_YET","SELF_REPORTED_ENROLLED_INSTALLATIONS"):
        raise ValueError("Unknown origin")
    if d["network_status"] not in ("COORDINATOR_REPORT","AWAITING_FIRST_PUBLIC_EXPORT"):
        raise ValueError("Unknown network state")
    for key in ("verified_unique_people","model_weights_shared","federated_models_enabled"):
        if d[key] is not False:raise ValueError("Incorrect verified or federated claim")
    if d["fleet_accuracy_percent"] is not None or d["countries"] is not None:
        raise ValueError("Unapproved fleet accuracy or country claims")
    groups=d["regions"]
    if not isinstance(groups,list) or len(groups)>len(PUBLIC_REGION_CENTERS):
        raise ValueError("Invalid public region list")
    seen_regions=set()
    for region in groups:
        fields=set(region) if isinstance(region,dict) else set()
        if fields not in (REGION_ROW,SINGLE_PUBLIC_REGION_ROW):
            raise ValueError("Unexpected regional data fields")
        code=region["code"]
        if not isinstance(code,str) or code not in PUBLIC_REGION_CENTERS or code in seen_regions:
            raise ValueError("Unrecognized/duplicate broad region")
        seen_regions.add(code)
        label,x,y=PUBLIC_REGION_CENTERS[code]
        if region["label"]!=label or type(region["x"]) is not int or type(region["y"]) is not int or (region["x"],region["y"])!=(x,y):
            raise ValueError("Region coordinates must be privacy-reviewed fixed macro centroids")
        if fields==SINGLE_PUBLIC_REGION_ROW:
            if region["visibility"]!="EXPLICIT_PUBLIC_OPT_IN":
                raise ValueError("Unapproved singleton visibility claim")
            integer(region["reporting_nodes"],1)
        else:
            integer(region["reporting_nodes"],10)
        if region["reporting_nodes"]>d["reporting_nodes"]:
            raise ValueError("Region count exceeds total reporting installations")
    if groups!=sorted(groups,key=lambda r:(-r["reporting_nodes"],r["code"])):
        raise ValueError("Regions must be deterministically ranked")
    if not isinstance(d["privacy_note"],str) or not 1<=len(d["privacy_note"])<=600:
        raise ValueError("Invalid privacy disclosure")
    if d["published_at_utc"] is not None:
        stamp=d["published_at_utc"]
        if not isinstance(stamp,str) or len(stamp)!=20 or not stamp.endswith("Z"):
            raise ValueError("Invalid export timestamp")
        datetime.strptime(stamp,"%Y-%m-%dT%H:%M:%SZ")
    integer(d["reporting_nodes"])
    rows=d["monthly"]
    if not isinstance(rows,list) or len(rows)>12:raise ValueError("Too many cohort rows")
    seen=set();qualified=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!=ROW:raise ValueError("Unapproved cohort fields")
        period=row["month"]
        if not isinstance(period,str) or len(period)!=7:raise ValueError("Bad cohort month")
        date=datetime.strptime(period,"%Y-%m")
        if date.strftime("%Y-%m")!=period or period in seen:raise ValueError("Duplicate/invalid cohort")
        seen.add(period)
        if row["label"]!=date.strftime("%b %Y"):raise ValueError("Invalid label")
        if row["status"]=="SHARED_GROUP":
            integer(row["reporting_nodes"],10)
            integer(row["predictions_checked"],1)
            measure(row["mean_error_f"])
            if row["reporting_nodes"]>d["reporting_nodes"]:raise ValueError("Cohort exceeds network")
            qualified.append(row)
        elif row["status"]=="SMALL_GROUP_PRIVATE":
            if any(row[x] is not None for x in ("reporting_nodes","predictions_checked","mean_error_f")):
                raise ValueError("Private monthly values leaked")
        else:raise ValueError("Bad monthly status")
    if [r["month"] for r in rows]!=sorted(r["month"] for r in rows):
        raise ValueError("Monthly series not sorted")
    latest=qualified[-1] if qualified else None
    if latest:
        if d["predictions_checked"]!=latest["predictions_checked"] or d["mean_error_f"]!=latest["mean_error_f"]:
            raise ValueError("Summary disagrees with cohort")
    elif d["predictions_checked"] is not None or d["mean_error_f"] is not None:
        raise ValueError("Unqualified summary")
    return json.loads(json.dumps(d,allow_nan=False))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=check(json.loads(a.input.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("PUBLIC SNAPSHOT PASS:",result["reporting_nodes"],"reporting nodes")
if __name__=="__main__":main()
