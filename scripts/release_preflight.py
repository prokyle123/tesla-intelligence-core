#!/usr/bin/env python3
"""Read-only source-tree readiness check for the Tesla Intelligence Core v1 release.

Run: python3 scripts/release_preflight.py [--strict]
No credentials, API calls, telemetry, or installed services are read.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent.parent
CORE = (
    "install.sh", "update.sh", "uninstall.sh", "VERSION", "README.md",
    "ghost_tesla_ai/tessie_source.py", "ghost_tesla_ai/winter_board.py",
    "ghost_tesla_ai/neural_governor.py", "web/templates/index.html",
)
V1 = (
    "web/templates/forecast_quality_v2.html",
    "web/templates/trip_quality_v32.html",
    "web/templates/ghost_vehicle_sensors.html",
    "ghost_tesla_ai/vehicle_sensors_v1.py",
    "ghost_tesla_ai/forecast_quality_v2_api.py",
    "ghost_tesla_ai/trip_quality_v3_api.py",
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="nonzero exit until the v1 feature set exists in the tree")
    args = parser.parse_args()
    missing_core = [p for p in CORE if not (ROOT / p).is_file()]
    missing_v1 = [p for p in V1 if not (ROOT / p).is_file()]
    print("Tesla Intelligence Core v1 release preflight (source only)")
    print("Core source:", "PASS" if not missing_core else "MISSING: " + ", ".join(missing_core))
    print("v1 web/API components:", "PASS" if not missing_v1 else "NOT YET MERGED: " + ", ".join(missing_v1))
    for key, paths in (("ghost_tesla_ai/", ROOT / "ghost_tesla_ai"),
                       ("web/templates/", ROOT / "web" / "templates")):
        print(f"{key}: {sum(1 for p in paths.rglob('*') if p.is_file()) if paths.exists() else 0} files")
    if missing_core or (args.strict and missing_v1):
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
