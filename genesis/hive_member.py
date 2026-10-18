"""Off-by-default real Hive monthly reporting from existing GHOST outcomes.

The ONLY transmitted facts are month, count, rounded sum of absolute
battery-temperature forecast errors. No VIN, GPS, car_id, state, route,
raw samples, exact times, model files or model parameters.

Manual consent + explicit upload; no background timers. HTTPS required
except loopback development. Server operators can see submitted aggregates
from one pseudonymous registered installation: NOT anonymous.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import quote

from .hive_monthly import SCHEMA,METRIC,validate_aggregate
from .hive_transfer import _endpoint

POLICY="MONTHLY_BATTERY_TEMP_ERROR_V1"
STATE_NAME="real-consent.json"
RECEIPT_NAME="last-receipt.json"

class ConsentError(ValueError):pass


def _dir(root:Path,*,create:bool=False)->Path:
    r=Path(root).expanduser().absolute()
    if r.is_symlink() or (r.exists() and (not r.is_dir() or r.stat().st_mode & 0o077)):
        raise ConsentError("Consent directory must be a private real directory (0700)")
    if create:
        r.mkdir(parents=True,exist_ok=True,mode=0o700)
    return r


def _read_private(file:Path)->str:
    if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077:
        raise ConsentError("Consent/token file missing or not private (0600)")
    return file.read_text()


def _put(root:Path,name:str,data:dict):
    r=_dir(root,create=True)
    f=r/name
    if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o077):
        raise ConsentError("Refusing unsafe consent state file")
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix=".hive-consent-",dir=r)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as stream:
            json.dump(data,stream,sort_keys=True)
        os.replace(tmp,f)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def _config(root:Path)->dict:
    r=_dir(root)
    file=r/STATE_NAME
    if not file.is_file():
        return {"mode":"OFF","configured":False,"policy":POLICY}
    raw=_read_private(file)
    data=json.loads(raw)
    if data.get("mode") not in ("OFF","OPTED_IN") or data.get("policy")!=POLICY:
        raise ConsentError("Unknown consent state; refusing upload")
    return data


def configure(root:Path,endpoint:str,token_file:Path)->dict:
    """Prepare address and credential, without granting upload permission."""
    url=_endpoint(endpoint)
    key=Path(token_file).expanduser().absolute()
    if key.is_symlink():raise ConsentError("Credential symlinks forbidden")
    secret=_read_private(key).strip()
    if not 40<=len(secret)<=200:raise ConsentError("Invalid private enrollment token")
    _put(root,STATE_NAME,{"mode":"OFF","configured":True,"policy":POLICY,
                          "endpoint":url,"token_file":str(key)})
    return status(root)


def consent(root:Path,*,acknowledged:bool=False)->dict:
    if not acknowledged:
        raise ConsentError("Affirmative aggregate-sharing acknowledgement required")
    c=_config(root)
    if not c.get("configured") or not c.get("token_file"):
        raise ConsentError("Configure a private coordinator and token first")
    if c["mode"]!="OPTED_IN":
        c["mode"]="OPTED_IN"
        _put(root,STATE_NAME,c)
    return status(root)


def disable(root:Path)->dict:
    c=_config(root)
    if c.get("configured"):
        c["mode"]="OFF"
        _put(root,STATE_NAME,c)
    return status(root)


def status(root:Path)->dict:
    c=_config(root)
    result={"mode":c["mode"],"configured":bool(c.get("configured")),
            "explicit_real_consent":c["mode"]=="OPTED_IN",
            "automatic_uploads":False,
            "data_fields":["schema","metric","month","scored_predictions",
                           "total_abs_error_c","source"],
            "gps":False,"raw_trips":False,"vin":False,
            "model_weights":False,
            "privacy":"PSEUDONYMOUS_AGGREGATE_NOT_ANONYMOUS"}
    r=Path(root).expanduser().absolute()
    f=r/RECEIPT_NAME
    if f.is_file():
        receipt=json.loads(_read_private(f))
        result["last_success_month"]=receipt.get("month")
        result["last_success_at_utc"]=receipt.get("time_utc")
    return result


def _month_range(month:str)->tuple[float,float]:
    if not re.fullmatch(r"20[2-9]\d-(0[1-9]|1[0-2])",month):
        raise ConsentError("Expected UTC month YYYY-MM")
    year,mo=map(int,month.split("-"))
    following=(year+1,1) if mo==12 else (year,mo+1)
    return (datetime(year,mo,1,tzinfo=timezone.utc).timestamp(),
            datetime(*following,1,tzinfo=timezone.utc).timestamp())


def preview(source:Path,*,month:str|None=None)->dict:
    """Read production SQLite in URI ro and query_only mode. Never write."""
    month=month or datetime.now(timezone.utc).strftime("%Y-%m")
    start,end=_month_range(month)
    p=Path(source).expanduser().resolve()
    if not p.is_file():raise ConsentError("GHOST source database missing")
    con=sqlite3.connect("file:"+quote(str(p),safe="/")+"?mode=ro",
                        uri=True,timeout=4)
    try:
        con.execute("PRAGMA query_only=ON")
        names={r[1] for r in con.execute("PRAGMA table_info(prediction_audit)")}
        needed={"resolved_at","status","target_field","abs_error"}
        if not needed.issubset(names):
            raise ConsentError("Prediction audit columns missing")
        cols={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
        if "car_id" in cols and con.execute(
            "SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]>1:
            raise ConsentError("Multiple vehicles cannot be combined under one enrollment")
        n,error=con.execute("""SELECT COUNT(*),SUM(abs_error)
            FROM prediction_audit
            WHERE status='resolved' AND target_field='battery_temp_c'
              AND abs_error IS NOT NULL AND abs_error>=0 AND abs_error<=30
              AND resolved_at>=? AND resolved_at<?""",(start,end)).fetchone()
    finally:
        con.close()
    # Threshold and no exact events makes upload payload coarse.
    if n<25:
        return {"eligible":False,"month":month,"scored_predictions":int(n),
                "reason":"At least 25 locally resolved battery-temperature forecasts required",
                "payload":None}
    payload=validate_aggregate({
        "schema":SCHEMA,"metric":METRIC,"month":month,
        "scored_predictions":int(n),"total_abs_error_c":round(float(error),2),
        "source":"ghost_prediction_audit"})
    return {"eligible":True,"month":month,"scored_predictions":n,
            "payload":payload,
            "warning":"Server can associate your monthly statistic with an enrolled installation. Not anonymous."}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ConsentError("Coordinator redirects are forbidden")


def send(root:Path,source:Path,*,month:str|None=None,confirm:bool=False)->dict:
    c=_config(root)
    if c["mode"]!="OPTED_IN":
        return {"sent":False,"reason":"EXPLICIT_OPT_IN_REQUIRED"}
    report=preview(source,month=month)
    if not report["eligible"]:
        return {"sent":False,"reason":"INSUFFICIENT_LOCAL_EVIDENCE",
                "scored_predictions":report["scored_predictions"]}
    if not confirm:
        return {"sent":False,"reason":"MANUAL_CONFIRMATION_REQUIRED",
                "preview":report}
    endpoint=_endpoint(c["endpoint"])
    key=Path(c["token_file"])
    token=_read_private(key).strip()
    payload=json.dumps(report["payload"],sort_keys=True,separators=(",",":")).encode()
    request=Request(endpoint+"/v1/monthly-research",method="POST",data=payload,
          headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
    # No system proxy; no cross-host 301/302 token forwarding.
    opener=build_opener(ProxyHandler({}),_NoRedirect())
    try:
        with opener.open(request,timeout=8) as response:
            obj=json.load(response)
            if response.status!=202 or obj.get("accepted") is not True:
                raise ConsentError("Coordinator did not acknowledge report")
    except (HTTPError,URLError) as exc:
        raise ConsentError("Coordinator rejected upload or network unavailable") from exc
    _put(root,RECEIPT_NAME,{"month":report["month"],
                            "time_utc":datetime.now(timezone.utc).isoformat(),
                            "schema":SCHEMA})
    return {"sent":True,"month":report["month"],"scored_predictions":report["scored_predictions"],
            "received":"ACCEPTED_BY_COORDINATOR",
            "can_revoke_server":"Ask coordinator to revoke this enrollment token"}


def revoke_remote(root:Path,*,confirm:bool=False)->dict:
    """Immediately stop local uploads; request remote deletion if confirmed."""
    c=_config(root)
    disable(root)
    if not confirm:
        return {"disabled_locally":True,"remote_deleted":False,
                "action":"REQUIRES_EXPLICIT_REMOTE_DELETION_CONFIRMATION"}
    if not c.get("configured") or not c.get("endpoint"):
        return {"disabled_locally":True,"remote_deleted":False,
                "action":"NO_ENROLLMENT_CONFIGURED"}
    endpoint=_endpoint(c["endpoint"])
    token=_read_private(Path(c["token_file"])).strip()
    req=Request(endpoint+"/v1/enrollment",method="DELETE",
                headers={"Authorization":"Bearer "+token})
    opener=build_opener(ProxyHandler({}),_NoRedirect())
    try:
        with opener.open(req,timeout=8) as response:
            payload=json.load(response)
            if response.status!=200 or payload.get("revoked") is not True:
                raise ConsentError("Deletion not confirmed by coordinator")
    except (HTTPError,URLError) as exc:
        raise ConsentError("Locally disabled; remote deletion not confirmed") from exc
    return {"disabled_locally":True,"remote_deleted":True,
            "note":"Stored contributor aggregates erased; backups may be retained under the server's retention policy."}


def main(argv=None)->int:
    p=argparse.ArgumentParser(description="GHOST Hive explicit real aggregate opt-in")
    p.add_argument("--state-dir",type=Path,required=True)
    p.add_argument("--source-db",type=Path,
                   default=Path("/var/lib/ghost-tesla-ai/ghost_ai.sqlite3"))
    sub=p.add_subparsers(dest="action",required=True)
    c=sub.add_parser("configure")
    c.add_argument("--endpoint",required=True)
    c.add_argument("--token-file",type=Path,required=True)
    g=sub.add_parser("consent")
    g.add_argument("--i-understand-pseudonymous-aggregate-sharing",
                   action="store_true",required=True)
    sub.add_parser("disable")
    remote=sub.add_parser("revoke-remote")
    remote.add_argument("--confirm-delete",action="store_true")
    sub.add_parser("status")
    v=sub.add_parser("preview")
    v.add_argument("--month",default=None)
    s=sub.add_parser("send")
    s.add_argument("--month",default=None)
    s.add_argument("--confirm-upload",action="store_true")
    a=p.parse_args(argv)
    actions={
        "configure":lambda:configure(a.state_dir,a.endpoint,a.token_file),
        "consent":lambda:consent(a.state_dir,acknowledged=a.i_understand_pseudonymous_aggregate_sharing),
        "disable":lambda:disable(a.state_dir),
        "revoke-remote":lambda:revoke_remote(a.state_dir,confirm=a.confirm_delete),
        "status":lambda:status(a.state_dir),
        "preview":lambda:preview(a.source_db,month=a.month),
        "send":lambda:send(a.state_dir,a.source_db,month=a.month,confirm=a.confirm_upload),
    }
    print(json.dumps(actions[a.action](),indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
