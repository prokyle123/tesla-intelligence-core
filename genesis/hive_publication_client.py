"""Explicit, revocable publication of coarse MONTHLY scores from one node.

Separate consent from the original aggregate transport and regional consent.
Never exports raw forecast events, locations, credential contents or VINs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import URLError,HTTPError

from . import hive_member as member

STATE="monthly-publication.json"

def status(root:Path)->dict:
    p=Path(root).expanduser().absolute()/STATE
    try:
        if p.is_symlink() or not p.is_file():raise ValueError("Missing state")
        data=json.loads(member._read_private(p))
        return {"public_monthly":data.get("public_monthly") is True}
    except (OSError,ValueError,member.ConsentError,json.JSONDecodeError):
        return {"public_monthly":False}

def update(root:Path,enabled:bool)->dict:
    path=member._dir(root,create=True)
    config=member._config(path)
    if not config.get("configured"):
        raise member.ConsentError("Hive enrollment must be configured")
    if enabled and (config.get("mode")!="OPTED_IN" or config.get("schedule")!="hourly"):
        raise member.ConsentError("Active hourly cohort consent required")
    endpoint=member._endpoint(config["endpoint"])
    token=member._read_private(Path(config["token_file"])).strip()
    body={"schema":"ghost-hive-monthly-public-v1","acknowledge_public_from_one":True}
    req=Request(endpoint+"/v1/monthly-publication",
        method="PUT" if enabled else "DELETE",
        data=json.dumps(body,separators=(",",":")).encode() if enabled else None,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    try:
        with build_opener(ProxyHandler({}),member._NoRedirect()).open(req,timeout=8) as resp:
            result=json.load(resp)
            if resp.status not in (200,202):
                raise member.ConsentError("Public monthly update not accepted")
    except (HTTPError,URLError) as exc:
        raise member.ConsentError("Coordinator unavailable or does not support public monthly consent") from exc
    if enabled and not (result.get("accepted") is True and result.get("public_monthly") is True):
        raise member.ConsentError("Public monthly permission not acknowledged")
    if not enabled and not (result.get("deleted") is True and result.get("public_monthly") is False):
        raise member.ConsentError("Public monthly withdrawal not confirmed")
    member._put(path,STATE,{"public_monthly":enabled})
    return {"public_monthly":enabled,"monthly_scope":"APPROVED_AGGREGATE_ONLY",
            "nonconsenting_member_data_included":False}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--state-dir",type=Path,required=True)
    p.add_argument("action",choices=("publish","hide","status"))
    p.add_argument("--acknowledge-single-monthly",action="store_true")
    args=p.parse_args(argv)
    try:
        if args.action=="status":result=status(args.state_dir)
        elif args.action=="hide":result=update(args.state_dir,False)
        else:
            if not args.acknowledge_single_monthly:
                raise member.ConsentError("Separate public small-cohort permission is required")
            result=update(args.state_dir,True)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (member.ConsentError,OSError,ValueError):
        print("PUBLIC_MONTHLY_PERMISSION_NOT_CHANGED",file=sys.stderr)
        return 1
if __name__=="__main__":
    raise SystemExit(main())
