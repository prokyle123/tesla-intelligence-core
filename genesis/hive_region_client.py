"""Separately authorized Hive broad-region sharing, not inferred geolocation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import URLError,HTTPError

from . import hive_member as member
from .hive_regions import REGION_SCHEMA,REGIONS

REGION_STATE="regional-consent.json"

def update(root:Path,code:str|None)->dict:
    path=member._dir(root,create=True)
    config=member._config(path)
    if not config.get("configured"):
        raise member.ConsentError("Hive enrollment must be configured")
    if code is not None:
        if code not in REGIONS:raise member.ConsentError("Unsupported broad region")
        if config.get("mode")!="OPTED_IN" or config.get("schedule")!="hourly":
            raise member.ConsentError("Hourly aggregate opt-in required before regional sharing")
    endpoint=member._endpoint(config["endpoint"])
    token=member._read_private(Path(config["token_file"])).strip()
    req=Request(endpoint+"/v1/region",
                method="PUT" if code is not None else "DELETE",
                data=json.dumps({"schema":REGION_SCHEMA,"region_code":code},sort_keys=True).encode() if code is not None else None,
                headers={"Authorization":"Bearer "+token,
                         "Content-Type":"application/json"})
    opener=build_opener(ProxyHandler({}),member._NoRedirect())
    try:
        with opener.open(req,timeout=8) as response:
            obj=json.load(response)
            if response.status not in (200,202):
                raise member.ConsentError("Region request not accepted")
    except (URLError,HTTPError) as exc:
        raise member.ConsentError("Private Hive coordinator unavailable for region update") from exc
    if code is not None:
        if obj.get("accepted") is not True:raise member.ConsentError("Region not accepted")
        member._put(path,REGION_STATE,{"region_code":code,"enabled":True})
    else:
        if obj.get("deleted") is not True:raise member.ConsentError("Region deletion not confirmed")
        (path/REGION_STATE).unlink(missing_ok=True)
    return {"regional_sharing":"OPTED_IN" if code else "OFF",
            "region_label":REGIONS[code][0] if code else None,
            "region_code":code,"exact_location_shared":False}

def status(root:Path)->dict:
    try:
        p=Path(root).expanduser().absolute()/REGION_STATE
        if p.is_file() and not p.is_symlink():
            data=json.loads(member._read_private(p))
            if data.get("enabled") is True and data.get("region_code") in REGIONS:
                return {"region_code":data["region_code"],"region_label":REGIONS[data["region_code"]][0]}
    except (OSError,ValueError,member.ConsentError,json.JSONDecodeError):
        pass
    return {"region_code":None,"region_label":None}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",type=Path,required=True)
    parser.add_argument("action",choices=("set","clear","status"))
    parser.add_argument("--region-code",choices=sorted(REGIONS))
    args=parser.parse_args(argv)
    try:
        if args.action=="status":result=status(args.state_dir)
        elif args.action=="clear":result=update(args.state_dir,None)
        else:
            if not args.region_code:raise member.ConsentError("Region selection required")
            result=update(args.state_dir,args.region_code)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (member.ConsentError,OSError,ValueError):
        print("HIVE_REGION_UPDATE_FAILED",file=sys.stderr)
        return 1
if __name__=="__main__":
    raise SystemExit(main())
