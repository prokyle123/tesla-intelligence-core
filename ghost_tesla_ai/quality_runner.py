"""Portable read-only evaluator entrypoint for automated systemd quality timers.

Only orchestrates evaluation against local telemetry and frozen predictions.
Never calls Tessie, changes model state, or writes to the vehicle database.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
import subprocess
import sys

from . import config

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "release-sidecars"


def command(kind: str) -> list[str]:
    db = config.DB_PATH
    quality_dir = Path(config.get("GHOST_QUALITY_DIR", str(config.DATA_DIR / "quality")))
    sidecar_db = Path(config.get(
        "GHOST_TRIP_OUTCOMES_DB",
        str(config.DATA_DIR / "trip-sequence" / "prediction-eval-v3.sqlite3"),
    ))
    if kind == "forecast":
        return [
            sys.executable, str(SCRIPTS / "evaluate_v2.py"),
            "--db", str(db),
            "--v1", str(SCRIPTS / "evaluate.py"),
            "--out", str(quality_dir),
            "--days", "7",
        ]
    if kind == "trip":
        return [
            sys.executable, str(SCRIPTS / "evaluate_v32.py"),
            "--db", str(db),
            "--sidecar", str(sidecar_db),
            "--out", str(quality_dir),
            "--days", "7",
        ]
    raise ValueError("Unsupported evaluator: " + kind)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tesla Intelligence Core shadow evaluator")
    parser.add_argument("kind", choices=("forecast", "trip"))
    parser.add_argument("--check", action="store_true", help="Validate files and paths without running evaluation")
    args = parser.parse_args(argv)
    cmd = command(args.kind)
    if not config.DB_PATH.is_file():
        parser.error("No telemetry DB yet (wait for collector): " + str(config.DB_PATH))
    if not Path(cmd[1]).is_file():
        parser.error("Missing installed evaluator: " + cmd[1])
    # A fresh install starts with an empty database. Waiting for real records
    # is normal, and must not mark a scheduled one-shot evaluation as failed.
    try:
        with sqlite3.connect("file:" + str(config.DB_PATH) + "?mode=ro", uri=True, timeout=4) as con:
            has_telemetry = con.execute("SELECT 1 FROM telemetry LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        has_telemetry = False
    if not has_telemetry:
        print("WAITING: collector has not recorded usable telemetry yet.")
        return 0
    if args.kind == "forecast" and not (SCRIPTS / "evaluate.py").is_file():
        parser.error("Missing base forecast evaluator")
    if args.check:
        print("Evaluator ready:", args.kind)
        return 0
    output = Path(config.get("GHOST_QUALITY_DIR", str(config.DATA_DIR / "quality")))
    oldmask = os.umask(0o077)
    try:
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.run(cmd, cwd=ROOT, check=True)
    finally:
        os.umask(oldmask)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
