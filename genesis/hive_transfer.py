"""GENESIS Hive opt-in transfer client.

OFF by default. Explicit operator configuration is required, and every
network submission requires --send. Only allowlisted synthetic test
aggregates can leave the client in this development milestone.

We intentionally do NOT transfer real historic or prospective per-car
statistics yet; the Hive backend sees per-member aggregates and is not
cryptographic secure aggregation, differential privacy or anonymity.
"""
from __future__ import annotations

from datetime import datetime,timezone
import argparse
import ipaddress
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error

from .hive_protocol import SCHEMA,METRIC,validate

VERSION="HIVE_CLIENT_0.1"
DEFAULT_MODE="OFF"


def _private_root(path: Path)->Path:
    p=Path(path).expanduser().absolute()
    if p.is_symlink():
        raise ValueError("Hive client directory must not be a symlink.")
    p.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.stat().st_mode & 0o077:
        raise ValueError("Hive client directory must be 0700.")
    return p


def _local_only(host: str)->bool:
    if host in ("localhost","127.0.0.1","::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint(value: str)->str:
    obj=urllib.parse.urlsplit(value)
    if (obj.username or obj.password or obj.fragment or obj.query
        or obj.path not in ("","/")
        or not obj.hostname or obj.scheme not in ("https","http")
        or (obj.scheme=="http" and not _local_only(obj.hostname))):
        raise ValueError("Hive endpoint requires HTTPS, except literal loopback development.")
    if obj.port is not None and not 1024<=obj.port<=65535:
        raise ValueError("Hive port outside allowed range.")
    return value.rstrip("/")


def _config_file(root: Path)->Path:
    return root/"consent.json"


def _read(root: Path)->dict:
    f=_config_file(root)
    if not f.is_file():
        return {"mode":"OFF","configured":False}
    if f.is_symlink() or f.stat().st_mode & 0o077:
        raise ValueError("Consent config must have private 0600 permissions.")
    v=json.loads(f.read_text())
    if v.get("mode") not in ("OFF","SYNTHETIC_TEST"):
        raise ValueError("Unsupported consent mode.")
    return v


def configure(root: Path, *, endpoint: str, token_file: Path,
              test_opt_in: bool=False)->dict:
    """User action only. Enabling synthetic transport does not transmit."""
    directory=_private_root(root)
    url=_endpoint(endpoint)
    key=Path(token_file).expanduser().resolve()
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077:
        raise ValueError("Token must exist in a private 0600 file.")
    token=key.read_text().strip()
    if not 40<=len(token)<=200:
        raise ValueError("Invalid bearer token.")
    document={"mode":"SYNTHETIC_TEST" if test_opt_in else "OFF",
              "endpoint":url,"token_file":str(key),"version":VERSION}
    file=_config_file(directory)
    fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600) if not file.exists() else os.open(file,os.O_WRONLY|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump(document,f,sort_keys=True)
    return status(root)


def disable(root: Path)->dict:
    directory=_private_root(root)
    file=_config_file(directory)
    # Do not delete credentials or rewrite report history. The user's
    # explicit local opt-out immediately blocks transfer attempts.
    data=_read(directory)
    data["mode"]="OFF"
    if not file.exists():
        return status(root)
    file.write_text(json.dumps(data,sort_keys=True))
    file.chmod(0o600)
    return status(root)


def status(root: Path)->dict:
    cfg=_read(Path(root))
    return {"service":"GENESIS_HIVE_CLIENT","mode":cfg["mode"],
            "configured":bool(cfg.get("configured",True) if cfg["mode"]!="OFF" else "endpoint" in cfg),
            "real_telemetry_uploads":False,
            "automatic_uploads":False,
            "fleet_models_enabled":False,
            "secure_aggregation":False,
            "differential_privacy":False,
            "caution":"Only synthetic test aggregates are eligible for transport in this preview."}


def payload_for_test(period: str|None=None)->dict:
    period=period or datetime.now(timezone.utc).strftime("%Y-%m")
    return validate({"schema":SCHEMA,"metric":METRIC,"period":period,
                     "episodes":25,"mae_c":0.75,"origin":"synthetic"})


def send(root: Path,*,transmit: bool=False,period: str|None=None)->dict:
    cfg=_read(Path(root))
    if cfg["mode"]!="SYNTHETIC_TEST":
        return {"status":"BLOCKED_NOT_OPTED_IN","network_request":False}
    body=payload_for_test(period)
    if not transmit:
        return {"status":"DRY_RUN_NO_NETWORK","network_request":False,
                "schema":body["schema"],"origin":body["origin"],"metric":body["metric"]}
    endpoint=_endpoint(cfg["endpoint"])
    key=Path(cfg["token_file"])
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077:
        raise ValueError("Private token no longer readable.")
    token=key.read_text().strip()
    raw=json.dumps(body,separators=(",",":"),sort_keys=True).encode()
    req=urllib.request.Request(endpoint+"/v1/contributions",data=raw,method="POST",
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req,timeout=8) as response:
            reply=json.load(response)
            if response.status!=202 or reply.get("accepted") is not True:
                raise ValueError("Hive did not acknowledge contribution.")
    except urllib.error.URLError as exc:
        raise RuntimeError("Hive transport failed; no successful receipt.") from exc
    return {"status":"SYNTHETIC_AGGREGATE_ACCEPTED","network_request":True,
            "real_telemetry_uploads":False,"origin":"synthetic"}


def main(argv=None):
    p=argparse.ArgumentParser(description="Explicitly opt-in Hive test transfer client")
    p.add_argument("--state-dir",type=Path,required=True)
    subs=p.add_subparsers(dest="command",required=True)
    cfg=subs.add_parser("configure")
    cfg.add_argument("--endpoint",required=True)
    cfg.add_argument("--token-file",type=Path,required=True)
    cfg.add_argument("--enable-synthetic",action="store_true")
    subs.add_parser("disable")
    subs.add_parser("status")
    push=subs.add_parser("send-test")
    push.add_argument("--send",action="store_true",
                      help="Actually transmit the synthetic aggregate (default dry-run)")
    args=p.parse_args(argv)
    if args.command=="configure":
        response=configure(args.state_dir,endpoint=args.endpoint,
                           token_file=args.token_file,
                           test_opt_in=args.enable_synthetic)
    elif args.command=="disable":
        response=disable(args.state_dir)
    elif args.command=="status":
        response=status(args.state_dir)
    else:
        response=send(args.state_dir,transmit=args.send)
    print(json.dumps(response,sort_keys=True,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
