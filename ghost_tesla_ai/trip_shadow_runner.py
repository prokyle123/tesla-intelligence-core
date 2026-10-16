"""Run the six existing shadow trip learners in dependency order.

Writes only private sidecars under the configured data directory.
No Tesla actions, production prediction changes or automatic promotion.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from . import config

LAYERS=(
 ("sequence_v1","trip_sequence_shadow",("--db","{db}","--out","{root}")),
 ("location_v2","trip_location_context",("--root","{root}")),
 ("outcomes_v3","trip_outcome_v3",("--root","{root}","--live-db","{db}")),
 ("feedback_v4","trip_feedback_v4",("--root","{root}")),
 ("coverage_v5","trip_coverage_v5",("--root","{root}","--db","{db}")),
 ("relationships_v6","trip_relationship_v6",("--root","{root}","--db","{db}")),
)

def commands(db,root):
    values={"{db}":str(db),"{root}":str(root)}
    return [(name,[sys.executable,"-m","ghost_tesla_ai."+module]+
             [values.get(x,x) for x in flags]) for name,module,flags in LAYERS]

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--check",action="store_true")
    args=ap.parse_args(argv)
    db=config.DB_PATH
    root=Path(config.get("GHOST_TRIP_SHADOW_DIR",str(config.DATA_DIR/"trip-sequence")))
    if args.check:
        for name,command in commands(db,root):
            print(name,command[2])
        return 0
    if not db.is_file():
        print("No vehicle database yet: trip shadow learning will wait.")
        return 0
    old_umask=os.umask(0o077)
    try:
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        results=[]
        for name,command in commands(db,root):
            started=time.monotonic()
            try:
                status=subprocess.run(command,cwd=Path(__file__).resolve().parent.parent,
                                      capture_output=True,text=True,timeout=240).returncode
            except subprocess.TimeoutExpired:
                status=124
            results.append({"layer":name,"status":"ok" if status==0 else "failed",
                            "exit_code":status,"seconds":round(time.monotonic()-started,1)})
            print(name+": "+results[-1]["status"])
            if status: break
        record={"shadow_only":True,"generated_epoch":time.time(),
                "all_ok":len(results)==len(LAYERS) and all(r["exit_code"]==0 for r in results),
                "layers":results}
        dest=root/"pipeline-status.json"
        temp=root/".pipeline-status.tmp"
        temp.write_text(json.dumps(record,indent=2)+"\n")
        os.chmod(temp,0o600)
        os.replace(temp,dest)
        return 0 if record["all_ok"] else 1
    finally:
        os.umask(old_umask)

if __name__=="__main__":
    raise SystemExit(main())
