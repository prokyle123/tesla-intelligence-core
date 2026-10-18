#!/usr/bin/env python3
"""Guarded upgrade of the ALREADY managed, loopback Hive coordinator service.

Strictly preserves existing systemd supervision, accepted contributions, all
consent state and GHOST production. Stages a pinned git archive and backs up
SQLite with the SQLite backup API. Never creates a second coordinator. If the
new process fails verification, restores the old unit and previous release.
DB is not blindly restored: no schema migration is planned for this upgrade.
"""
from __future__ import annotations
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from hive_coordinator_managed_rollout import (
    DB,PY,UNIT,SERVICE,STAGED,BACKUPS,checked,source_rev,unit_text,
    _stage,_db_counts,_online_backup
)

def _current_unit():
    if UNIT.is_symlink() or not UNIT.is_file():
        raise RuntimeError("Existing managed coordinator service unit not found")
    user=pwd.getpwuid(os.getuid()).pw_name
    raw=UNIT.read_bytes()
    service=subprocess.run(
        ["systemctl","is-active","--quiet",SERVICE],check=False)
    if service.returncode:
        raise RuntimeError("Existing managed coordinator service not active")
    text=raw.decode("utf-8")
    prefix="WorkingDirectory="
    values=[x.removeprefix(prefix) for x in text.splitlines()
            if x.startswith(prefix)]
    if len(values)!=1:
        raise RuntimeError("Unexpected managed service working directory")
    old=Path(values[0])
    if not old.is_relative_to(STAGED) or old.is_symlink() or not old.is_dir():
        raise RuntimeError("Managed coordinator is not running a pinned release")
    revision=(old/"COMMIT").read_text().strip()
    if len(revision)!=40 or old!=STAGED/revision:
        raise RuntimeError("Managed coordinator revision cannot be verified")
    if raw!=unit_text(old,user).encode("utf-8"):
        raise RuntimeError("Unexpected unit modifications; manual review required")
    if _db_counts()["integrity"]!="ok":
        raise RuntimeError("SQLite integrity check failed")
    return old,revision,raw,user


def _wait_server(expected:int, *,new_endpoint:bool):
    for _ in range(26):
        try:
            with urlopen("http://127.0.0.1:8778/health",timeout=2) as r:
                health=json.load(r)
            with urlopen("http://127.0.0.1:8778/v1/public-network",timeout=2) as r:
                network=json.load(r)
            if (health.get("ok") is not True or
                network.get("reporting_nodes")!=expected or
                _db_counts()["enrolled"]!=expected):
                raise RuntimeError("Coordinator enrollment mismatch")
            if new_endpoint:
                try:
                    urlopen("http://127.0.0.1:8778/v1/member-comparison",timeout=2)
                    raise RuntimeError("Private comparison exposed without bearer token")
                except HTTPError as denied:
                    if denied.code!=401:
                        raise RuntimeError("Private comparison route wrong auth status")
            return
        except (OSError,ValueError,sqlite3.Error):
            time.sleep(1)
    raise RuntimeError("Coordinator readiness/authentication verification timed out")


def _put_unit(raw:bytes):
    with tempfile.NamedTemporaryFile("wb",prefix="hive-managed-unit-",delete=False) as tmp:
        tmp.write(raw)
        name=tmp.name
    try:
        checked("sudo","install","-o","root","-g","root","-m","0644",
                name,str(UNIT))
    finally:
        Path(name).unlink(missing_ok=True)
    checked("sudo","systemctl","daemon-reload")


def execute(apply:bool):
    if os.geteuid()==0:
        raise RuntimeError("Run as regular GHOST owner, not root")
    revision=source_rev()
    old,oldrev,oldbytes,user=_current_unit()
    prior=_db_counts()
    print("MANAGED COORDINATOR:",oldrev[:12])
    print("REVIEWED SOURCE:",revision)
    print("ENROLLED REPORTING INSTALLATIONS:",prior["enrolled"])
    print("SAVED MONTHLY ROWS:",prior["monthly"])
    print("PUBLIC REGION PERMISSIONS PRESERVED:",prior["regions"])
    print("BACKUP PATH:",str(BACKUPS))
    if not apply:
        print("MANAGED HIVE UPGRADE CHECK PASS — NO CHANGES")
        return
    if revision==oldrev:
        raise RuntimeError("Coordinator already running the requested revision")
    checked("sudo","-v")
    updated=_stage(revision)
    unit=unit_text(updated,user).encode("utf-8")
    BACKUPS.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(BACKUPS,0o700)
    reserve=Path(tempfile.mkdtemp(prefix="coordinator-release-",dir=BACKUPS))
    os.chmod(reserve,0o700)
    (reserve/"previous-unit.service").write_bytes(oldbytes)
    (reserve/"previous-unit.service").chmod(0o600)
    _online_backup(DB,reserve/"hive-before-release.sqlite3")
    archived=_db_counts(reserve/"hive-before-release.sqlite3")
    if any(archived[k]!=prior[k] for k in ("enrolled","monthly","regions")):
        raise RuntimeError("Online SQLite backup does not match enrollment")
    # No overlap between old and new binders; unit is updated only after stop.
    stopped=False
    try:
        # Recheck immediately before service interruption.
        latest,live_rev,live_bytes,_=_current_unit()
        if live_rev!=oldrev or live_bytes!=oldbytes:
            raise RuntimeError("Coordinator changed before cutover")
        checked("sudo","systemctl","stop",SERVICE)
        stopped=True
        _put_unit(unit)
        checked("sudo","systemctl","start",SERVICE)
        _wait_server(prior["enrolled"],new_endpoint=True)
        now=_db_counts()
        if any(now[k]!=prior[k] for k in ("enrolled","monthly","regions")):
            raise RuntimeError("Unexpected enrollment/contribution count change")
        if UNIT.read_bytes()!=unit:
            raise RuntimeError("Managed coordinator unit changed unexpectedly")
        print("M12 MANAGED COORDINATOR UPGRADE PASS")
        print("Installed revision:",revision)
        print("Preserved enrolled installations:",now["enrolled"])
        print("Snapshot backup:",reserve/"hive-before-release.sqlite3")
        print("Previous pinned service backup:",reserve/"previous-unit.service")
    except BaseException:
        if stopped:
            print("FAILED: restoring previous managed coordinator service",file=sys.stderr)
            try:
                subprocess.run(["sudo","systemctl","stop",SERVICE],check=False)
                _put_unit(oldbytes)
                checked("sudo","systemctl","start",SERVICE)
                _wait_server(prior["enrolled"],new_endpoint=False)
                print("RESTORED previous service:",oldrev[:12])
            except BaseException as rescue:
                print("CRITICAL: automated service recovery uncertain:",
                      type(rescue).__name__,str(rescue)[:140],
                      "backup:",reserve,file=sys.stderr)
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("check","install"))
    a=parser.parse_args()
    try:
        execute(a.action=="install")
    except (RuntimeError,OSError,ValueError,sqlite3.Error,
            subprocess.CalledProcessError) as exc:
        print("STOP:",type(exc).__name__,str(exc)[:180],file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
