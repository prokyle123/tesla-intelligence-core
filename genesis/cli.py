"""Local-only Genesis research command interface. No scheduling or network calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .hivemind import network_status
from .fleet_simulator import simulate_fleet
from .research import discover
from .source import SourceUnavailable, load_numeric_history
from .store import ResearchStore

def run_once(source_db: Path, research_db: Path, max_rows: int = 6000) -> dict:
    source_db = Path(source_db).expanduser().resolve()
    research_db = Path(research_db).expanduser().resolve()
    if research_db == source_db:
        raise ValueError("Research storage may not be the production database.")
    rows = load_numeric_history(source_db, limit=max_rows)
    found = discover(rows)
    run_id = ResearchStore(research_db).save(source_db, len(rows), found)
    return {
        "status": "RESEARCH_ONLY", "run_id": run_id, "telemetry_rows": len(rows),
        "evaluated": len(found), "shadow_candidates": sum(h.status == "SHADOW" for h in found),
        "production_changes": False, "hivemind_uploads": False,
    }

def overview(research_db: Path) -> dict:
    store = ResearchStore(research_db)
    return {
        "module": "GHOST GENESIS", "version": "0.1.0",
        "research_mode": "LOCAL_SHADOW_ONLY", "network": network_status(),
        "runs": store.recent_runs(20), "findings": store.recent_findings(25),
        "production_changes": False,
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Experimental offline GHOST GENESIS lab")
    p.add_argument("--source-db", type=Path, default=config.source_db())
    p.add_argument("--research-db", type=Path, default=config.research_db())
    commands = p.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-once", help="One explicit, read-only research cycle")
    run.add_argument("--max-rows", type=int, default=6000)
    commands.add_parser("status", help="Show research runs and privacy settings")
    commands.add_parser("hivemind-status", help="Inspect disabled-by-default fleet controls")
    demo = commands.add_parser("simulate-fleet", help="Run a synthetic offline global-model learning demo")
    demo.add_argument("--nodes", type=int, default=32)
    demo.add_argument("--rounds", type=int, default=30)
    args = p.parse_args(argv)
    try:
        if args.command == "run-once":
            result = run_once(args.source_db, args.research_db, args.max_rows)
        elif args.command == "status":
            result = overview(args.research_db)
        elif args.command == "simulate-fleet":
            result = simulate_fleet(vehicles=args.nodes, rounds=args.rounds)
        else:
            result = network_status()
    except (SourceUnavailable, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
