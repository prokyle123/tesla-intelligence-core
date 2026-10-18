#!/usr/bin/env python3
"""Guarded, scoped PIN-gateway+Hive owner authorization update; no model files.

Only reviewed predecessor source bytes or an absent new proof module are
accepted. Unknown edits stop. All changes are backed up with checksums and
rollback needs an exact installed checksum.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import py_compile
import stat
import tempfile

FILES=(
    "ghost_tesla_ai/hive_local.py",
    "ghost_tesla_ai/funnel_gateway.py",
    "ghost_tesla_ai/hive_owner_proof.py",
)
OLD_GIT_BLOBS={
    "ghost_tesla_ai/hive_local.py":{
        "fe335c75c2d0536d1b0a0035a6fb3e244e31e33e"},
    "ghost_tesla_ai/funnel_gateway.py":{
        "6ec6a77a26a2971c5ff5c402577101d2700b0ebb"},
    "ghost_tesla_ai/hive_owner_proof.py":set(),
}
NEW_FILE="ghost_tesla_ai/hive_owner_proof.py"

def sha(content:bytes)->str:
    return hashlib.sha256(content).hexdigest()

def blob(content:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()

def _atomic(path:Path, content:bytes, *, mode:int, uid:int, gid:int)->None:
    fd,tmp=tempfile.mkstemp(prefix=".hive-owner-stage-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp,mode)
        if hasattr(os,"chown"):os.chown(tmp,uid,gid)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def plan(live:Path,source:Path,backup:Path):
    if not live.is_dir() or live.is_symlink() or not source.is_dir():
        raise ValueError("Installed GHOST and reviewed source required.")
    if backup.exists():
        raise ValueError("Fresh private rollback directory required.")
    changes={}
    for name in FILES:
        old=live/name
        new=source/name
        if not new.is_file() or new.is_symlink() or old.is_symlink():
            raise ValueError("Missing reviewed source or unsafe symbolic link: "+name)
        exists=old.is_file()
        if not exists and (old.exists() or name!=NEW_FILE):
            raise ValueError("Missing/unexpected installed file: "+name)
        present=old.read_bytes() if exists else None
        wanted=new.read_bytes()
        if exists and present!=wanted and blob(present) not in OLD_GIT_BLOBS[name]:
            raise ValueError("Unreviewed local edits block update: "+name)
        changes[name]=(present,wanted)
    return changes

def apply(live:Path,source:Path,backup:Path, *, dry_run:bool):
    changes=plan(live,source,backup)
    for name,(old,new) in changes.items():
        print(("New:" if old is None else "Scoped update:" if old!=new else "Unchanged:"),
              name, sha(old)[:12] if old is not None else "(absent)",
              "->",sha(new)[:12])
    if dry_run:
        print("OWNER GATEWAY CHECK PASS — NO FILES MODIFIED")
        return
    backup.mkdir(mode=0o700)
    backup.chmod(0o700)
    manifest={"files":{}}
    installed=[]
    try:
        for i,(name,(old,new)) in enumerate(changes.items()):
            dest=live/name
            owner=dest.stat() if old is not None else (live/"ghost_tesla_ai/hive_local.py").stat()
            mode=stat.S_IMODE(owner.st_mode) if old is not None else 0o644
            original=None
            if old is not None:
                original=f"original-{i}.bak"
                fd=os.open(backup/original,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,"wb") as f:f.write(old)
            manifest["files"][name]={
                "original_sha256":sha(old) if old is not None else None,
                "installed_sha256":sha(new),
                "original_backup":original,
                "original_mode":mode,
                "uid":owner.st_uid,"gid":owner.st_gid,
            }
        (backup/"latest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        (backup/"latest.json").chmod(0o600)
        for name,(old,new) in changes.items():
            if old==new:continue
            item=manifest["files"][name]
            _atomic(live/name,new,mode=item["original_mode"],
                    uid=item["uid"],gid=item["gid"])
            installed.append(name)
        for name in FILES:
            py_compile.compile(str(live/name),doraise=True)
    except Exception:
        # Restore only source files this tool just modified.
        for name in reversed(installed):
            record=manifest["files"][name]
            old=changes[name][0]
            if old is None:
                (live/name).unlink(missing_ok=True)
            else:
                _atomic(live/name,old,mode=record["original_mode"],
                        uid=record["uid"],gid=record["gid"])
        (backup/"latest.json").rename(backup/"failed-rolled-back.json")
        raise
    print("HIVE OWNER GATEWAY PATCH APPLIED — restart only web and existing PIN gateway.")

def rollback(live:Path,backup:Path):
    manifest=json.loads((backup/"latest.json").read_text())
    if set(manifest["files"])!=set(FILES):
        raise ValueError("Unexpected rollback scope")
    for name in FILES:
        record=manifest["files"][name]
        dest=live/name
        if dest.is_symlink() or not dest.is_file() or sha(dest.read_bytes())!=record["installed_sha256"]:
            raise ValueError("Refusing rollback of unknown installed source: "+name)
        old=record["original_backup"]
        if old and sha((backup/old).read_bytes())!=record["original_sha256"]:
            raise ValueError("Original checksum mismatch: "+name)
    for name in FILES:
        record=manifest["files"][name]
        old=record["original_backup"]
        if old:
            _atomic(live/name,(backup/old).read_bytes(),
                    mode=record["original_mode"],uid=record["uid"],gid=record["gid"])
        else:
            (live/name).unlink()
    (backup/"latest.json").rename(backup/"restored.json")
    print("HIVE OWNER GATEWAY PATCH ROLLED BACK.")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--live",type=Path,required=True)
    parser.add_argument("--backup",type=Path,required=True)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--rollback",action="store_true")
    a=parser.parse_args()
    live=a.live.expanduser().resolve()
    source=Path(__file__).resolve().parents[1]
    backup=a.backup.expanduser().absolute()
    if a.rollback:rollback(live,backup)
    else:apply(live,source,backup,dry_run=a.check)
if __name__=="__main__":main()
