"""Read-only private Hive member comparison client.

Uses the EXISTING explicitly configured Hive endpoint and enrollment token.
Never sends a new research field, writes to coordinator, or changes consent.
Authenticated peer scores are already aggregation/release-gated server-side.
"""
from __future__ import annotations
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError, HTTPError

from . import hive_member as member
from .hive_peer_comparison import SCHEMA

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def read(root:Path, *,timeout:float=1.8)->dict:
    state=member._config(Path(root))
    if state.get("mode")!="OPTED_IN" or not state.get("configured"):
        return {"schema":SCHEMA,"status":"NOT_ENROLLED","months":[]}
    endpoint=member._endpoint(state["endpoint"])
    key=Path(state["token_file"]).expanduser().absolute()
    token=member._read_private(key).strip()
    if not 40<=len(token)<=200:
        raise member.ConsentError("Invalid enrolled Hive token")
    req=Request(endpoint+"/v1/member-comparison",method="GET",
                headers={"Authorization":"Bearer "+token,
                         "Accept":"application/json"})
    try:
        with build_opener(ProxyHandler({}),_NoRedirect()).open(
                req,timeout=timeout) as resp:
            if resp.status!=200 or resp.headers.get_content_type()!="application/json":
                raise member.ConsentError("Unexpected Hive comparison response")
            if resp.headers.get("Content-Length") and int(resp.headers["Content-Length"])>24000:
                raise member.ConsentError("Oversized Hive comparison response")
            raw=resp.read(24001)
            if len(raw)>24000:raise member.ConsentError("Oversized Hive response")
    except (OSError,URLError,HTTPError,ValueError) as exc:
        raise member.ConsentError("Private Hive comparison temporarily unavailable") from exc
    payload=json.loads(raw)
    if (not isinstance(payload,dict) or payload.get("schema")!=SCHEMA or
        payload.get("scope")!="AUTHENTICATED_INSTALLATION_ONLY" or
        payload.get("self_excluded_from_peers") is not True or
        not isinstance(payload.get("months"),list) or len(payload["months"])>12):
        raise member.ConsentError("Invalid authenticated comparison format")
    # Strictly return only reviewed aggregate keys, never user records or
    # coordinator secrets even if a future server changes its payload.
    fields=("schema","scope","status","latest_month","latest","months",
            "self_excluded_from_peers","peer_metric","source","limitations",
            "can_promote","network_uploads")
    return {k:payload[k] for k in fields if k in payload}


def main(argv=None)->int:
    import argparse
    import sys
    p=argparse.ArgumentParser(description="Read-only personal Hive peer comparison")
    p.add_argument("--state-dir",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        print(json.dumps(read(args.state_dir),sort_keys=True))
        return 0
    except (OSError,ValueError,member.ConsentError):
        print("HIVE_PEER_COMPARISON_UNAVAILABLE",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
