#!/usr/bin/env python3
"""Conservative patch installer for the current customized Classic GHOST.

Adds one /hive Blueprint registration and one tab, installs new isolated
Hive backend/template files. Does NOT rewrite, reformat, regenerate, or
overwrite the rest of the existing Home index/server. Backs up touched
files byte-for-byte and offers checked rollback. NO automatic restart.

Use a matched reviewed repo checkout. --check is read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import stat
import tempfile
import time


SERVER_ANCHOR=(
    "from .trip_quality_v3_api import bp as ghost_trip_quality_v3_bp\n"
    "app.register_blueprint(ghost_trip_quality_v3_bp)"
)
SERVER_ADDITION=(
    SERVER_ANCHOR+"\n"
    "from .hive_local import bp as ghost_hive_local_bp\n"
    "app.register_blueprint(ghost_hive_local_bp)"
)
TAB_ANCHOR=(
    '<a class="tab" href="/vehicle-sensors" '
    'style="display:inline-flex;align-items:center;text-decoration:none">'
    'Vehicle Sensors</a>'
)
TAB_ADDITION=TAB_ANCHOR+(
    '\n      <a class="tab" href="/hive" '
    'style="display:inline-flex;align-items:center;text-decoration:none">Hive</a>'
)
PATHS=(
    "ghost_tesla_ai/server.py","web/templates/index.html",
    "ghost_tesla_ai/hive_local.py","web/templates/hive.html",
)


def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(dest:Path,data:bytes):
    dest.parent.mkdir(parents=True,exist_ok=True)
    old=dest.stat() if dest.exists() else None
    fd,name=tempfile.mkstemp(prefix=".ghost-hive-",dir=dest.parent)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        mode=stat.S_IMODE(old.st_mode) if old else 0o644
        os.chmod(name,mode)
        if old and hasattr(os,"chown"):
            os.chown(name,old.st_uid,old.st_gid)
        os.replace(name,dest)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _plan(root:Path,source:Path)->dict[str,tuple[bytes|None,bytes]]:
    before={}
    for name in PATHS:
        f=root/name
        if f.is_symlink():
            raise ValueError(f"Refusing to change symlink: {name}")
        before[name]=f.read_bytes() if f.exists() else None
    if not before["ghost_tesla_ai/server.py"] or not before["web/templates/index.html"]:
        raise ValueError("Existing Classic dashboard/server required")
    try:
        server=before["ghost_tesla_ai/server.py"].decode("utf-8")
        index=before["web/templates/index.html"].decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Classic source text is not valid UTF-8") from exc
    if SERVER_ANCHOR not in server or server.count(SERVER_ANCHOR)!=1:
        raise ValueError("STOP: Live web server registration differs from reviewed source")
    if TAB_ANCHOR not in index or index.count(TAB_ANCHOR)!=1:
        raise ValueError("STOP: Live dashboard navigation differs from reviewed source")
    if 'ghost_hive_local_bp' in server or 'href="/hive"' in index:
        raise ValueError("Hive already integrated; refusing duplicate or overwrite")
    if before["ghost_tesla_ai/hive_local.py"] is not None or before["web/templates/hive.html"] is not None:
        raise ValueError("Existing Hive modules/templates found; inspect manually first")
    new={
        "ghost_tesla_ai/server.py":server.replace(SERVER_ANCHOR,SERVER_ADDITION,1).encode(),
        "web/templates/index.html":index.replace(TAB_ANCHOR,TAB_ADDITION,1).encode(),
        "ghost_tesla_ai/hive_local.py":(source/"ghost_tesla_ai/hive_local.py").read_bytes(),
        "web/templates/hive.html":(source/"web/templates/hive.html").read_bytes(),
    }
    return {name:(before[name],new[name]) for name in PATHS}


def _manifest(backup:Path):
    p=backup/"latest.json"
    if not p.exists():
        raise ValueError("No Hive integration backup manifest found")
    obj=json.loads(p.read_text())
    if sorted(obj.get("files",{}))!=sorted(PATHS):
        raise ValueError("Unexpected backup manifest scope")
    return obj


def _safety_backup_root(backup:Path, root:Path):
    if backup.is_symlink() or backup.resolve()==root.resolve():
        raise ValueError("Unsafe backup path")
    if backup.exists() and (backup.stat().st_mode & 0o077):
        raise ValueError("Backup directory permissions must be private (0700)")


def apply(root:Path,source:Path,backup:Path,*,dry_run=False):
    changes=_plan(root,source)
    for name,(old,new) in changes.items():
        print(f"{name}: {'new file' if old is None else 'additive patch'}, new sha256 {sha(new)[:16]}")
    if dry_run:
        print("CHECK PASS — no files or services changed")
        return
    _safety_backup_root(backup,root)
    backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(backup,0o700)
    if (backup/"latest.json").exists():
        raise ValueError("Existing backup manifest found: rollback/review before applying again")
    run=backup/("backup-"+time.strftime("%Y%m%d-%H%M%S"))
    run.mkdir(mode=0o700)
    data={"version":1,"files":{},"backup":run.name}
    for name,(old,new) in changes.items():
        if old is not None:
            path=run/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(old)
            os.chmod(path,0o600)
        data["files"][name]={
            "original_sha256":sha(old) if old is not None else None,
            "installed_sha256":sha(new),
        }
    try:
        for name,(_old,new) in changes.items():
            _atomic_write(root/name,new)
        for name in ("ghost_tesla_ai/server.py","ghost_tesla_ai/hive_local.py"):
            # Syntax only; do NOT import or execute production web server here.
            py_compile.compile(str(root/name),doraise=True)
        (backup/"latest.json").write_text(json.dumps(data,indent=2))
        os.chmod(backup/"latest.json",0o600)
    except Exception:
        for name,(old,_new) in changes.items():
            if old is None:
                (root/name).unlink(missing_ok=True)
            else:
                _atomic_write(root/name,old)
        raise
    print("HIVE PATCH APPLIED. No service restarted. Backup:",run)
    print("Exactly one existing nav link and one Flask Blueprint registration added.")


def rollback(root:Path,backup:Path):
    _safety_backup_root(backup,root)
    obj=_manifest(backup)
    run=backup/obj["backup"]
    if run.is_symlink() or not run.is_dir():
        raise ValueError("Backup run directory not available")
    # Fail before changing anything if any installed file was modified.
    for name in PATHS:
        path=root/name
        if path.is_symlink() or not path.exists():
            raise ValueError("Installed file unavailable for safe rollback: "+name)
        if sha(path.read_bytes())!=obj["files"][name]["installed_sha256"]:
            raise ValueError("File changed after install; manual reconciliation needed: "+name)
    for name in PATHS:
        original=obj["files"][name]["original_sha256"]
        if original is None:
            (root/name).unlink()
        else:
            saved=run/name
            if sha(saved.read_bytes())!=original:
                raise ValueError("Backup checksum mismatch: "+name)
            _atomic_write(root/name,saved.read_bytes())
    (backup/"latest.json").rename(run/"restored-manifest.json")
    print("HIVE ROLLBACK COMPLETE. Production services not restarted.")


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--backup",type=Path,required=True)
    cmd=p.add_mutually_exclusive_group(required=True)
    cmd.add_argument("--check",action="store_true")
    cmd.add_argument("--apply",action="store_true")
    cmd.add_argument("--rollback",action="store_true")
    args=p.parse_args(argv)
    source=Path(__file__).resolve().parent.parent
    root=args.root.expanduser().resolve()
    backup=args.backup.expanduser().absolute()
    if args.rollback:rollback(root,backup)
    else:apply(root,source,backup,dry_run=args.check)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
