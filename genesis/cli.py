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
from .validation import retrospective_audit
from .coverage import coverage_report
from .history_audit import distributed_coverage
from .history_samples import historical_blocks
from .architect import architect_cycle
from .architect_store import ArchitectLedger

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

def latest_discoveries(research_db: Path) -> dict:
    """Metadata only: summarize accepted evidence from the latest research run."""
    store = ResearchStore(research_db)
    runs = store.recent_runs(1)
    run = runs[0] if runs else None
    return {
        "module": "GHOST GENESIS", "research_mode": "LOCAL_SHADOW_ONLY",
        "latest_run_id": run["id"] if run else None,
        "evaluated": run["evaluated"] if run else 0,
        "shadow_candidates": run["shadows"] if run else 0,
        "rejected": (run["evaluated"] - run["shadows"]) if run else 0,
        "findings": store.shadow_findings(100),
        "interpretation": "Exploratory associations only; not independently validated discoveries.",
        "production_changes": False,
        "hivemind_uploads": False,
    }


def overview(research_db: Path) -> dict:
    store = ResearchStore(research_db)
    return {
        "module": "GHOST GENESIS", "version": "0.1.1",
        "research_mode": "LOCAL_SHADOW_ONLY", "network": network_status(),
        "runs": store.recent_runs(20), "findings": store.recent_findings(25),
        "production_changes": False,
    }

def audit_candidates(source_db: Path, research_db: Path,
                     max_rows: int = 12000, recent_window: int = 6000) -> dict:
    """Read-only retrospective check on previously selected shadow pairs."""
    if max_rows <= recent_window or max_rows > 12000:
        raise ValueError("Audit must include older records and remain within the 12,000-row cap.")
    found = ResearchStore(research_db).shadow_findings(40)
    if not found:
        return {
            "status":"NO_CANDIDATES", "results":[],
            "production_changes":False, "hivemind_uploads":False,
            "note":"An existing GENESIS research run with shadow findings is required.",
        }
    rows = load_numeric_history(source_db, limit=max_rows)
    pairs = [(f["feature"],f["target"]) for f in found]
    return retrospective_audit(rows,pairs,recent_window)


def inspect_coverage(source_db: Path, max_rows: int = 12000) -> dict:
    """No research DB reads or writes, only local aggregate evidence counts."""
    rows = load_numeric_history(source_db,limit=max_rows)
    return coverage_report(rows)


def historical_coverage(source_db: Path, research_db: Path,
                        blocks: int = 5, rows_per_block: int = 2400) -> dict:
    """Read disjoint bounded historical windows; never change either database."""
    shadows = ResearchStore(research_db).shadow_findings(40)
    pairs = [(item["feature"],item["target"]) for item in shadows]
    return distributed_coverage(source_db,pairs,blocks,rows_per_block)


def architect_once(source_db: Path, research_db: Path, architect_db: Path,
                   *, save: bool = False, blocks: int = 5,
                   rows_per_block: int = 2400) -> dict:
    """Propose and challenge hypotheses with fixed safe recipes and older eras."""
    source_db=Path(source_db).expanduser().resolve()
    research_db=Path(research_db).expanduser().resolve()
    architect_db=Path(architect_db).expanduser().resolve()
    if architect_db in {source_db,research_db}:
        raise ValueError("Architect results must be isolated from GHOST data and the prior research ledger.")
    history=historical_blocks(source_db,blocks,rows_per_block)
    # The fixed prototype requires exactly 3 training and 2 later test eras.
    report=architect_cycle(history)
    report["stored"]=False
    if save:
        run_id=ArchitectLedger(architect_db).save(report,(source_db,research_db))
        report["stored"]=True
        report["architect_run_id"]=run_id
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Experimental offline GHOST GENESIS lab")
    p.add_argument("--source-db", type=Path, default=config.source_db())
    p.add_argument("--research-db", type=Path, default=config.research_db())
    p.add_argument("--architect-db", type=Path, default=config.data_dir() / "architect.sqlite3")
    commands = p.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-once", help="One explicit, read-only research cycle")
    run.add_argument("--max-rows", type=int, default=6000)
    commands.add_parser("status", help="Show research runs and privacy settings")
    commands.add_parser("discoveries", help="Show only latest accepted local shadow candidates")
    audit = commands.add_parser("audit-candidates", help="Read-only retrospective evidence analysis")
    audit.add_argument("--max-rows", type=int, default=12000)
    audit.add_argument("--recent-window", type=int, default=6000)
    commands.add_parser("hivemind-status", help="Inspect disabled-by-default fleet controls")
    context = commands.add_parser("coverage", help="Read-only local signal and regime coverage")
    context.add_argument("--max-rows", type=int, default=12000)
    history = commands.add_parser("historical-coverage",
                                  help="Read-only multi-era regime and paired-data audit")
    history.add_argument("--blocks", type=int, default=5)
    history.add_argument("--rows-per-block", type=int, default=2400)
    architect = commands.add_parser("architect-once",
                  help="Generate, evaluate and prioritize safe research plans using 5 historical eras")
    architect.add_argument("--rows-per-block", type=int, default=2400)
    architect.add_argument("--save", action="store_true",
                  help="Explicitly save aggregate trial outcomes in independent local Architect SQLite")
    commands.add_parser("architect-status",help="Read last saved local Architect plans")
    demo = commands.add_parser("simulate-fleet", help="Run a synthetic offline global-model learning demo")
    demo.add_argument("--nodes", type=int, default=32)
    demo.add_argument("--rounds", type=int, default=30)
    args = p.parse_args(argv)
    try:
        if args.command == "run-once":
            result = run_once(args.source_db, args.research_db, args.max_rows)
        elif args.command == "status":
            result = overview(args.research_db)
        elif args.command == "discoveries":
            result = latest_discoveries(args.research_db)
        elif args.command == "audit-candidates":
            result = audit_candidates(args.source_db,args.research_db,args.max_rows,args.recent_window)
        elif args.command == "simulate-fleet":
            result = simulate_fleet(vehicles=args.nodes, rounds=args.rounds)
        elif args.command == "coverage":
            result = inspect_coverage(args.source_db,args.max_rows)
        elif args.command == "historical-coverage":
            result = historical_coverage(args.source_db,args.research_db,
                                         args.blocks,args.rows_per_block)
        elif args.command == "architect-once":
            result = architect_once(args.source_db,args.research_db,
                                    args.architect_db,save=args.save,
                                    rows_per_block=args.rows_per_block)
        elif args.command == "architect-status":
            result = ArchitectLedger(args.architect_db).latest()
        else:
            result = network_status()
    except (SourceUnavailable, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
