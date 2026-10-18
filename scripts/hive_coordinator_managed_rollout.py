#!/usr/bin/env python3
"""Guarded Hive coordinator migration to a persistent, pinned systemd service.

Only the verified user-owned port 8778 coordinator is stopped; no GHOST web,
collector, GENESIS preview, Hive hourly timer or consent source is modified.
Backup uses sqlite3.backup() with no active coordinator writer. On failure,
stop the new service, restore the backup and relaunch exact previous argv/cwd.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

from hive_coordinator_rollout_probe import (
    DB,EXPECTED_PORT,find_listening_pid,parse_argv,report as audit,
)

HOME=Path.home()
BASE=HOME/"genesis-product"
SOURCE=Path(__file__).resolve().parents[1]
STAGED=BASE/"coordinator-releases"
BACKUPS=BASE/"state/hive-coordinator-backups"
SERVICE="ghost-hive-coordinator.service"
UNIT=Path("/etc/systemd/system")/SERVICE
PY=Path("/opt/ghost-tesla-ai/venv/bin/python")

def checked(*args, **kwargs):
    return subprocess.run(args,check=True,text=True,**kwargs)

def source_rev()->str:
    if checked("git","-C",str(SOURCE),"status","--porcelain",
               capture_output=True).stdout.strip():
        raise ValueError("Uncommitted changes block coordinator rollout")
    rev=checked("git","-C",str(SOURCE),"rev-parse","--verify","HEAD",
                capture_output=True).stdout.strip()
    if len(rev)!=40 or not all(x in "0123456789abcdef" for x in rev):
        raise ValueError("Invalid pinned source revision")
    return rev

def _db_counts(path=DB)->dict:
    with closing(sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=5)) as con:
        con.execute("PRAGMA query_only=ON")
        return {
            "enrolled":int(con.execute(
                "SELECT COUNT(*) FROM participants WHERE enabled=1").fetchone()[0]),
            "monthly":int(con.execute(
                "SELECT COUNT(*) FROM monthly_research").fetchone()[0]),
            "regions":int(con.execute(
                "SELECT COUNT(*) FROM region_consents").fetchone()[0]),
            "public_schema":"public_listing" in {
                r[1] for r in con.execute("PRAGMA table_info(region_consents)")},
            "integrity":con.execute("PRAGMA integrity_check").fetchone()[0],
        }

def _online_backup(source:Path, dest:Path)->None:
    # Both SQLite source and destination are opened with the engine's online
    # backup API. Never copy the main .sqlite3 while a WAL may be active.
    fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
    os.close(fd)
    with closing(sqlite3.connect(source,timeout=10)) as orig, \
         closing(sqlite3.connect(dest,timeout=10)) as copy:
        orig.backup(copy,pages=200,sleep=.01)
    os.chmod(dest,0o600)
    if _db_counts(dest)["integrity"]!="ok":
        raise RuntimeError("Backup SQLite integrity check failed")

def _restore_backup(backup:Path,dest:Path)->None:
    # Target must not have a running writer. Preserve original live inode.
    with closing(sqlite3.connect(backup,timeout=10)) as src, \
         closing(sqlite3.connect(dest,timeout=10)) as out:
        src.backup(out,pages=200,sleep=.01)

def unit_text(release:Path,user:str)->str:
    if not user.isidentifier() or not release.is_relative_to(STAGED):
        raise ValueError("Invalid managed coordinator identity")
    return f"""[Unit]
Description=GHOST Hive Private Coordinator
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={release}
Environment=PYTHONUNBUFFERED=1
ExecStart={PY} -m genesis.hive_server --db {DB} --port {EXPECTED_PORT} serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=12
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths={DB.parent}

[Install]
WantedBy=multi-user.target
"""

def _owned_process():
    pid=find_listening_pid()
    proc=Path("/proc")/str(pid)
    if proc.stat().st_uid!=os.getuid():
        raise RuntimeError("Coordinator process owner changed")
    argv=[s.decode("utf-8","replace") for s in
          (proc/"cmdline").read_bytes().split(b"\0") if s]
    parse_argv(argv)
    cwd=(proc/"cwd").resolve()
    allowed=(HOME/"genesis-product/releases").resolve()
    if not cwd.is_relative_to(allowed):
        raise RuntimeError("Coordinator is not the known old staged release")
    return pid,argv,cwd

def _wait_health(*,expected:int,public_schema:bool,seconds=25):
    import urllib.request
    for _ in range(seconds):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8778/health",timeout=2) as response:
                health=json.load(response)
            with urllib.request.urlopen(
                "http://127.0.0.1:8778/v1/public-network",timeout=2) as response:
                public=json.load(response)
            counts=_db_counts()
            if (health.get("ok") is True and
                public.get("reporting_nodes")==expected and
                counts["enrolled"]==expected and
                counts["public_schema"] is public_schema):
                return
        except (OSError,ValueError,sqlite3.Error):
            pass
        time.sleep(1)
    raise RuntimeError("Coordinator did not become healthy with preserved enrollments")

def _stage(revision:str)->Path:
    release=STAGED/revision
    if release.exists() or release.is_symlink():
        if not release.is_dir() or (release/"COMMIT").read_text().strip()!=revision:
            raise RuntimeError("Existing coordinator stage does not match")
        return release
    STAGED.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(STAGED,0o700)
    release.mkdir(mode=0o700)
    # Staging from a clean pinned checkout; do NOT change the research viewer.
    shutil.copytree(SOURCE/"genesis",release/"genesis",symlinks=False)
    (release/"COMMIT").write_text(revision+"\n")
    os.chmod(release,0o700)
    checked(str(PY),"-m","genesis.hive_server","--help",
            cwd=release,stdout=subprocess.DEVNULL)
    return release

def _install_unit(unit:str)->None:
    with tempfile.NamedTemporaryFile("w",prefix="ghost-hive-unit-",
                                     delete=False) as tmp:
        tmp.write(unit)
        path=Path(tmp.name)
    try:
        checked("sudo","install","-o","root","-g","root","-m","0644",
                str(path),str(UNIT))
    finally:
        path.unlink(missing_ok=True)
    checked("sudo","systemctl","daemon-reload")
    checked("sudo","systemctl","enable","--now",SERVICE)

def _remove_unit()->None:
    subprocess.run(["sudo","systemctl","stop",SERVICE],check=False)
    subprocess.run(["sudo","systemctl","disable",SERVICE],check=False)
    subprocess.run(["sudo","rm","-f","--",str(UNIT)],check=False)
    subprocess.run(["sudo","systemctl","daemon-reload"],check=False)

def _restart_previous(argv,cwd,log:Path)->None:
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"wb") as out:
        proc=subprocess.Popen(argv,cwd=cwd,start_new_session=True,
                              stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT)
    print("Restarted original coordinator process, PID",proc.pid)

def execute(*,apply:bool):
    if os.geteuid()==0:
        raise ValueError("Run as regular Ghost user, not root")
    rev=source_rev()
    pid,oldargs,oldcwd=_owned_process()
    old=_db_counts()
    if old["integrity"]!="ok" or old["enrolled"]<1:
        raise RuntimeError("Existing coordinator data invalid: stop")
    if UNIT.exists() or UNIT.is_symlink():
        raise RuntimeError("Managed Hive service already exists; refusing overwrite")
    print("PINNED SOURCE:",rev)
    print("EXISTING COORDINATOR:",pid,"OLD_RELEASE",str(oldcwd))
    print("ACTIVE REPORTERS:",old["enrolled"],"MONTHLY ROWS:",old["monthly"])
    print("REGION ROWS:",old["regions"],"PUBLIC SCHEMA:",old["public_schema"])
    if not apply:
        print("MANAGED COORDINATOR CHECK PASS — no process or DB changes")
        return
    checked("sudo","-v")  # sudo before any process is stopped
    release=_stage(rev)
    BACKUPS.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(BACKUPS,0o700)
    backupdir=Path(tempfile.mkdtemp(prefix="before-public-regions-",dir=BACKUPS))
    os.chmod(backupdir,0o700)
    original_log=backupdir/"recovered-coordinator.log"
    previous_stopped=False
    backup=None
    unit_started=False
    try:
        # Recheck PID and exact argv before disturbing the only coordinator.
        if _owned_process()!=(pid,oldargs,oldcwd):
            raise RuntimeError("Coordinator identity changed during staging")
        os.kill(pid,signal.SIGTERM)
        previous_stopped=True
        for attempt in range(15):
            try:
                listening=find_listening_pid()
                if listening!=pid:
                    raise RuntimeError("Unexpected new listener during cutover")
            except RuntimeError as exc:
                if "No single owned" in str(exc):
                    break
                raise
            time.sleep(1)
        else:
            raise RuntimeError("Original coordinator did not release loopback port")
        backup=backupdir/"hive-before-migration.sqlite3"
        _online_backup(DB,backup)
        if any(_db_counts(backup)[k]!=old[k] for k in ("enrolled","monthly","regions")):
            raise RuntimeError("Backup differs from original coordinator database")
        _install_unit(unit_text(release,os.getlogin() if False else
                                __import__("pwd").getpwuid(os.getuid()).pw_name))
        unit_started=True
        _wait_health(expected=old["enrolled"],public_schema=True)
        after=_db_counts()
        if any(after[k]!=old[k] for k in ("enrolled","monthly","regions")):
            raise RuntimeError("Enrollment or contribution rows changed during migration")
        print("MANAGED COORDINATOR INSTALL PASS")
        print("Service:",SERVICE)
        print("Enrolled installations preserved:",after["enrolled"])
        print("Public-singleton schema migrated:",after["public_schema"])
        print("Online SQLite recovery backup:",str(backup))
        print("Existing region choices remain NONPUBLIC until new owner permission.")
    except BaseException:
        if previous_stopped:
            print("COORDINATOR UPGRADE FAILED: attempting isolated recovery",file=sys.stderr)
            if UNIT.exists() or unit_started:
                _remove_unit()
            if backup is not None and backup.exists():
                _restore_backup(backup,DB)
            _restart_previous(oldargs,oldcwd,original_log)
            try:
                _wait_health(expected=old["enrolled"],public_schema=old["public_schema"])
                print("Original coordinator restored; no enrolments changed")
            except BaseException as failure:
                print("CRITICAL: old coordinator health uncertain:",type(failure).__name__,
                      "Recovery log:",original_log,file=sys.stderr)
        raise

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("check","install"))
    args=p.parse_args()
    try:
        execute(apply=args.action=="install")
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError,sqlite3.Error) as exc:
        print("STOP:",type(exc).__name__,str(exc)[:240],file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
