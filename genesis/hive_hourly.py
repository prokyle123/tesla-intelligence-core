"""Hourly OFF-by-default Hive research sync.

Each successful run replaces the SAME participant/month aggregate on the
coordinator. No raw telemetry, trips, location or model weights transmitted.
A sync compares the current monthly report with its last acknowledged digest:
if no new scored predictions were added, NO network call is made.

Run from a privileged service-user timer as a one-shot, not a web task.
Only prior explicit hourly consent can authorize network uploads.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

from . import hive_member as member

SYNC_STATE="hourly-sync.json"
LOCK_NAME=".hourly-worker.lock"


def fingerprint(payload:dict)->str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def run_once(state_dir:Path,source_db:Path,*,month:str|None=None)->dict:
    root=member._dir(state_dir,create=True)
    lock_file=root/LOCK_NAME
    if lock_file.is_symlink():
        raise member.ConsentError("Worker lock path unsafe")
    descriptor=os.open(lock_file,os.O_RDWR|os.O_CREAT|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        try: fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state":"ALREADY_RUNNING","network_request":False}
        cfg=member._config(root)
        if cfg.get("mode")!="OPTED_IN" or cfg.get("schedule")!="hourly":
            return {"state":"CONSENT_OFF","network_request":False}
        report_month=month or datetime.now(timezone.utc).strftime("%Y-%m")
        report=member.preview(source_db,month=report_month)
        if not report["eligible"]:
            return {"state":"NO_QUALIFYING_EVIDENCE","network_request":False}
        digest=fingerprint(report["payload"])
        marker=root/SYNC_STATE
        if marker.exists():
            prior=json.loads(member._read_private(marker))
            if prior.get("month")==report_month and prior.get("payload_sha256")==digest:
                return {"state":"UNCHANGED","network_request":False,
                        "month":report_month}
        # send() re-reads consent and recreates the exact approved payload.
        # It checks OPTED_IN again immediately before submission.
        sent=member.send(root,source_db,month=report_month,confirm=True)
        if sent.get("sent") is not True:
            return {"state":"NOT_SENT","network_request":False}
        member._put(root,SYNC_STATE,{
            "month":report_month,
            "payload_sha256":digest,
            "accepted_at_utc":datetime.now(timezone.utc).isoformat(),
        })
        return {"state":"ACCEPTED","network_request":True,
                "month":report_month,"scored_predictions":report["scored_predictions"]}
    finally:
        fcntl.flock(descriptor,fcntl.LOCK_UN)
        os.close(descriptor)


def main(argv=None):
    p=argparse.ArgumentParser(description="Single hourly GHOST Hive aggregate sync iteration")
    p.add_argument("--state-dir",type=Path,required=True)
    p.add_argument("--source-db",type=Path,default=Path("/var/lib/ghost-tesla-ai/ghost_ai.sqlite3"))
    args=p.parse_args(argv)
    try:
        result=run_once(args.state_dir,args.source_db)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (member.ConsentError,ValueError,OSError):
        print("HIVE_SYNC_RETRYABLE_ERROR: review local Hive diagnostics",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
