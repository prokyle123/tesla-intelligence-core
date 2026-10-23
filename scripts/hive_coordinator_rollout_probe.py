#!/usr/bin/env python3
"""Read-only preflight for safely upgrading an EXISTING Hive coordinator.

Never prints bearer tokens/PINs, reads or modifies enrollment records,
stops services, or changes a database. Deliberately refuses to recommend
any restart until the process owner, command and supervisor are understood.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
from urllib.request import urlopen
from contextlib import closing

HOME=Path.home()
DB=(HOME/"genesis-product/state/hive-server/hive.sqlite3").resolve()
EXPECTED_MODULE="genesis.hive_server"
EXPECTED_PORT=8778

def parse_argv(argv:list[str], expected_db:Path=DB)->dict:
    """No shell interpolation. No bearer/PIN/cookie arguments accepted."""
    if not argv or len(argv)>24:
        raise ValueError("Unexpected coordinator command")
    if not Path(argv[0]).name.startswith("python"):
        raise ValueError("Coordinator binary is not Python")
    if "-m" not in argv or argv[argv.index("-m")+1:argv.index("-m")+2]!=[EXPECTED_MODULE]:
        raise ValueError("Coordinator module is not genesis.hive_server")
    if argv.count("--db")!=1:
        raise ValueError("Coordinator database argument absent or duplicated")
    ix=argv.index("--db")
    if len(argv)<=ix+1 or Path(argv[ix+1]).expanduser().resolve()!=expected_db:
        raise ValueError("Unexpected coordinator DB path")
    if argv.count("--port")>1:
        raise ValueError("Duplicate port argument")
    if "--port" in argv:
        p=argv.index("--port")
        if len(argv)<=p+1 or argv[p+1]!=str(EXPECTED_PORT):
            raise ValueError("Unexpected coordinator port")
    if argv.count("serve")!=1 or argv[-1]!="serve":
        raise ValueError("Coordinator is not serving")
    if any(x in argv for x in ("--token","--secret","--password")):
        raise ValueError("Unexpected sensitive commandline argument")
    return {"module":EXPECTED_MODULE,"database_matches_expected":True,
            "port":EXPECTED_PORT,"command":"serve"}

def find_listening_pid()->int:
    cmd=["ss","-H","-ltnp","sport = :8778"]
    r=subprocess.run(cmd,text=True,capture_output=True,timeout=5,check=False)
    if r.returncode:
        raise RuntimeError("Cannot inspect port 8778 listener")
    lines=[x for x in r.stdout.splitlines() if re.search(r"127\.0\.0\.1:8778\b",x)]
    ids={int(x) for line in lines for x in re.findall(r"pid=(\d+)",line)}
    if len(lines)!=1 or len(ids)!=1:
        raise RuntimeError("No single owned loopback coordinator process found")
    return ids.pop()

def supervisor(cgroups:str)->str:
    service=re.findall(r"([A-Za-z0-9@_.-]+\.service)(?:/|$)",cgroups)
    return service[-1] if service else "NOT_IDENTIFIED"

def report():
    pid=find_listening_pid()
    proc=Path("/proc")/str(pid)
    stat=proc.stat()
    if stat.st_uid!=os.getuid():
        raise RuntimeError("Coordinator process is not owned by current Ghost user")
    args=[x.decode("utf-8","replace") for x in (proc/"cmdline").read_bytes().split(b"\0") if x]
    parsed=parse_argv(args)
    cwd=(proc/"cwd").resolve()
    allowed=(HOME/"genesis-product/releases").resolve()
    local=(HOME/"genesis-product-source").resolve()
    if not (cwd==local or cwd.is_relative_to(allowed)):
        raise RuntimeError("Coordinator working directory is not an approved Ghost source/release")
    live=(HOME/"genesis-product/current").resolve()
    group=supervisor((proc/"cgroup").read_text())
    if not DB.is_file() or DB.is_symlink():
        raise RuntimeError("Private coordinator database not a regular file")
    with closing(sqlite3.connect("file:"+str(DB)+"?mode=ro",uri=True,timeout=5)) as con:
        con.execute("PRAGMA query_only=ON")
        columns={r[1] for r in con.execute("PRAGMA table_info(region_consents)")}
        counted=con.execute("SELECT COUNT(*) FROM participants WHERE enabled=1").fetchone()[0]
        journal=con.execute("PRAGMA journal_mode").fetchone()[0]
    with urlopen("http://127.0.0.1:8778/health",timeout=4) as r:
        health=json.load(r)
    with urlopen("http://127.0.0.1:8778/v1/public-network",timeout=4) as r:
        network=json.load(r)
    if health.get("ok") is not True or network.get("reporting_nodes")!=counted:
        raise RuntimeError("Coordinator reports mismatch to private DB")
    result={"status":"READ_ONLY_PREFLIGHT_PASS",
            "coordinator_pid":pid,
            "coordinator_service_unit":group,
            "coordinator_working_directory":str(cwd),
            "staged_current_release":str(live),
            "working_directory_is_staged_current":cwd==live,
            "coordinator_command":parsed,
            "database":str(DB),
            "database_bytes":DB.stat().st_size,
            "database_journal":journal,
            "enrolled_installations":counted,
            "public_regions":len(network.get("regions") or []),
            "singleton_public_schema_installed":"public_listing" in columns,
            "gateway_unmodified":True,
            "automatic_restart_permitted":False,
            "production_changes":False,
            "network_uploads":False}
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=="__main__":
    try:
        report()
    except (OSError,ValueError,RuntimeError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status":"PREFLIGHT_STOP",
                          "error_type":type(exc).__name__,
                          "explanation":str(exc)[:240],
                          "changes":False}))
        raise SystemExit(2)
