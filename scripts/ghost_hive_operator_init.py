#!/usr/bin/env python3
"""Per-installation owner control key. No coordinator access or upload happens here.

For each install: unique local owner control key (0600) AND separate,
independently enrolled Hub bearer credential. Neither credential is a
public installation ID and neither belongs in Git or the browser storage.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets


def initialize(state_dir: Path) -> Path:
    root=Path(state_dir).expanduser().absolute()
    if root.is_symlink() or (root.exists() and (not root.is_dir() or root.stat().st_mode & 0o077)):
        raise ValueError("Hive state path must be a private 0700 directory, not a symlink")
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=root/"dashboard-admin.token"
    if key.exists() or key.is_symlink():
        if not key.is_file() or key.stat().st_mode & 0o077:
            raise ValueError("Existing owner key is not private (0600)")
        if len(key.read_text().strip())<40:
            raise ValueError("Existing owner key does not meet key-strength requirements")
        print("OWNER_KEY_EXISTS:",key)
        return key
    token=secrets.token_urlsafe(48)
    fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"w") as f:
        f.write(token+"\n")
    print("OWNER_KEY_CREATED:",key)
    print("Consent remains OFF. No Hive enrollment or transfer performed.")
    return key


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    initialize(args.state_dir)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
