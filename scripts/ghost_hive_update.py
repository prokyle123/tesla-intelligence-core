#!/usr/bin/env python3
"""Safely update only the two Hive-owned files on customized live GHOST.

--check writes nothing. --apply requires current files to match the original
reviewed Hive installation. --rollback verifies upgraded hashes first.
Never touches Home index, Classic server, training, Tesla database or timers.
Never restarts services.
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

FILES=("ghost_tesla_ai/hive_local.py","web/templates/hive.html")
# Explicitly reviewed prior Hive module versions; unknown custom edits block.
BASE_HASH_PREFIX={
    "ghost_tesla_ai/hive_local.py":("14f0fbee4285","61e13b57da06","be260bf1c765","995c7223a9e2"),
    "web/templates/hive.html":("a4aa5289c605","f427abbb67cb","964730ca8ed7","fa591e5a3221"),
}
# A prior deployed v1 UI had no SHA256 baseline registered. Its exact
# Git blob identity is public and verified from commit 98f65fbc; unlike
# prefix wildcards, this verifies *all* installed source bytes.
REVIEWED_PRIOR_GIT_BLOBS={
    "ghost_tesla_ai/hive_local.py":{"36573224ee008ce079ead3be7d67e12af38035f0"},
    "web/templates/hive.html":{"c13ae37fac325d6290570cb70579f67eeef14a8f"},
}

def git_blob_sha(data:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()



def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()


def _write(path:Path,contents:bytes):
    old=path.stat()
    fd,tmp=tempfile.mkstemp(prefix=".hive-upgrade-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as stream:stream.write(contents)
        os.chmod(tmp,stat.S_IMODE(old.st_mode))
        if hasattr(os,"chown"):os.chown(tmp,old.st_uid,old.st_gid)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def check(live:Path,source:Path,backup:Path):
    if backup.is_symlink():
        raise ValueError("Refusing a symlinked backup directory")
    if backup.exists() and backup.stat().st_mode & 0o077:
        raise ValueError("Backup directory not private (0700)")
    if (backup/"latest.json").exists():
        raise ValueError("Existing active Hive upgrade detected")
    changes={}
    for name in FILES:
        old=live/name
        new=source/name
        if old.is_symlink() or not old.is_file() or not new.is_file():
            raise ValueError("Hive file not found or symlinked: "+name)
        existing=old.read_bytes()
        wanted=new.read_bytes()
        prefixes=BASE_HASH_PREFIX[name]
        if isinstance(prefixes,str): prefixes=(prefixes,)  # test fixture
        known_sha256=any(sha(existing).startswith(prefix) for prefix in prefixes)
        known_git_blob=git_blob_sha(existing) in REVIEWED_PRIOR_GIT_BLOBS.get(name,set())
        if existing!=wanted and not (known_sha256 or known_git_blob):
            raise ValueError("Existing Hive module was already edited: "+name)
        changes[name]=(existing,wanted)
    if all(before==after for before,after in changes.values()):
        raise ValueError("Hive code already matches target, no update needed")
    return changes


def apply(live:Path,source:Path,backup:Path,*,dry_run:bool):
    data=check(live,source,backup)
    for name,(before,after) in data.items():
        print("Scoped update:" if before!=after else "Unchanged:",name,sha(before)[:12],"->",sha(after)[:12])
    if dry_run:
        print("CHECK PASS — no files modified")
        return
    backup.mkdir(parents=True,mode=0o700,exist_ok=True)
    os.chmod(backup,0o700)
    manifest={"files":{}}
    for i,(name,(before,after)) in enumerate(data.items()):
        f=backup/f"original-{i}.bak"
        fd=os.open(f,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as out:out.write(before)
        manifest["files"][name]={"original":sha(before),"installed":sha(after),"copy":f.name}
    (backup/"latest.json").write_text(json.dumps(manifest,indent=2))
    (backup/"latest.json").chmod(0o600)
    try:
        for name,(_before,after) in data.items():
            _write(live/name,after)
        py_compile.compile(str(live/"ghost_tesla_ai/hive_local.py"),doraise=True)
    except Exception:
        for name,(before,_after) in data.items():
            _write(live/name,before)
        (backup/"latest.json").unlink(missing_ok=True)
        raise
    print("HIVE MODULE UPDATE APPLIED; restart ONLY Classic GHOST web when approved.")


def rollback(live:Path,backup:Path):
    manifest=json.loads((backup/"latest.json").read_text())
    if set(manifest["files"])!=set(FILES):
        raise ValueError("Unexpected rollback file scope")
    for name in FILES:
        item=manifest["files"][name]
        if sha((live/name).read_bytes())!=item["installed"]:
            raise ValueError("Hive file modified since update: "+name)
        if sha((backup/item["copy"]).read_bytes())!=item["original"]:
            raise ValueError("Original backup checksum does not match: "+name)
    for name in FILES:
        _write(live/name,(backup/manifest["files"][name]["copy"]).read_bytes())
    (backup/"latest.json").rename(backup/"restored.json")
    print("HIVE MODULE ROLLBACK COMPLETE; restart only web service if running.")


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",type=Path,required=True)
    p.add_argument("--backup",type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    group.add_argument("--rollback",action="store_true")
    opts=p.parse_args(argv)
    src=Path(__file__).resolve().parent.parent
    live=opts.live.expanduser().resolve()
    backup=opts.backup.expanduser().absolute()
    if opts.rollback:rollback(live,backup)
    else:apply(live,src,backup,dry_run=opts.check)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
