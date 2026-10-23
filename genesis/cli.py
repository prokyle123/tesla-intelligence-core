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
from .conflict_mission import inspect_conflicts
from .thermal_mission import thermal_episode_challenge
from .episode_lab import parked_thermal_research
from .thermal_tournament import run_tournament
from .prospective_shadow import freeze_shadow, score_shadow, shadow_status
from .product_core import ProductLedger, run_product_cycle
from .prospective_truth_watch import freeze_watch, check_watch
from .truth_watch_history import record_history, read_history
from .frozen_challenger import freeze_challenger, challenger_status
from .episode_challenge import episode_challenge

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


def overview(research_db: Path, data_dir: Path | None = None) -> dict:
    store = ResearchStore(research_db)
    root = Path(data_dir) if data_dir is not None else config.data_dir()
    return {
        "module": "GHOST GENESIS", "version": "0.1.1",
        "research_mode": "LOCAL_SHADOW_ONLY", "network": network_status(),
        "runs": store.recent_runs(20), "findings": store.recent_findings(25),
        "architect": ArchitectLedger(root / "architect.sqlite3").latest(),
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


def mission_followup(source_db: Path, architect_db: Path,
                     rows_per_block: int = 2400) -> dict:
    """Execute the research mission selected by the latest Architect cycle.

    Pure read-only analytics, with no production effects. The saved mission is
    not allowed to specify code, arbitrary paths, APIs or any commands.
    """
    saved = ArchitectLedger(architect_db).latest()["run"]
    if not saved:
        return {
            "status":"NO_SAVED_ARCHITECT_MISSION",
            "note":"First run architect-once --save with private storage.",
            "production_changes":False,"fleet_uploads":False,
        }
    mission = saved["selected_next_mission"]["kind"]
    blocks=historical_blocks(source_db,blocks=5,rows_per_block=rows_per_block)
    if mission=="RESOLVE_SENSOR_CONTEXT":
        report=inspect_conflicts(blocks)
    elif mission=="CHALLENGE_SHADOW_MODEL":
        report=parked_thermal_research(source_db)
    else:
        # Only vetted mission types are executable; unknown/unapproved plans
        # cannot become network requests or dynamically loaded Python code.
        return {
            "status":"MANUAL_REVIEW_REQUIRED","selected_mission":mission,
            "note":"No vetted execution recipe for the selected research mission.",
            "production_changes":False,"fleet_uploads":False,
        }
    return {
        "status":"FOLLOWUP_COMPLETED_RESEARCH_ONLY",
        "architect_run_id":saved["id"],
        "selected_mission":mission,
        "followup":report,
        "production_changes":False,
        "fleet_uploads":False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Experimental offline GHOST GENESIS lab")
    p.add_argument("--source-db", type=Path, default=config.source_db())
    p.add_argument("--research-db", type=Path, default=config.research_db())
    p.add_argument("--architect-db", type=Path, default=config.data_dir() / "architect.sqlite3")
    p.add_argument("--shadow-db", type=Path,
                   default=config.data_dir() / "prospective_shadow.sqlite3")
    p.add_argument("--product-db", type=Path,
                   default=config.data_dir() / "product.sqlite3")
    p.add_argument("--truth-watch-file", type=Path,
                   default=config.data_dir() / "prospective-truth-watch.json")
    p.add_argument("--truth-history-db", type=Path,
                   default=config.data_dir() / "prospective-truth-history.sqlite3")
    p.add_argument("--challenger-file", type=Path,
                   default=config.data_dir() / "prospective-challenger.json")
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
    follow = commands.add_parser("mission-next",
                                help="Run vetted followup chosen by saved Architect research")
    follow.add_argument("--rows-per-block",type=int,default=2400)
    direct = commands.add_parser("mission-conflicts",
                                help="Read-only charger/speed conflict diagnostic")
    direct.add_argument("--rows-per-block",type=int,default=2400)
    thermal = commands.add_parser("mission-thermal",
                                 help="Read-only parked pack-temperature +60m challenge")
    thermal.add_argument("--rows-per-block",type=int,default=2400)
    thermal_full=commands.add_parser("mission-thermal-full",
                      help="Challenge a one-hour model across complete parked episodes")
    thermal_full.add_argument("--max-scan",type=int,default=100000)
    tour=commands.add_parser("thermal-tournament",
                             help="Challenge fixed thermal models on independent parked episodes")
    tour.add_argument("--max-scan",type=int,default=100000)
    frozen=commands.add_parser("shadow-freeze",
                 help="Explicitly freeze rejected thermal challenger for future diagnostics")
    frozen.add_argument("--max-scan",type=int,default=100000)
    check=commands.add_parser("shadow-check",
                 help="Score only completed post-freeze parked episodes")
    check.add_argument("--max-scan",type=int,default=100000)
    commands.add_parser("shadow-status",
                 help="Read status and aggregate history of frozen shadow")
    product = commands.add_parser("product-cycle",
                 help="Operator-invoked research cycle with isolated product history")
    product.add_argument("--max-scan",type=int,default=100000)
    product.add_argument("--save",action="store_true",
                         help="Save aggregate-only findings in private product ledger")
    commands.add_parser("product-status",help="Read local product research history")
    commands.add_parser("truth-watch-freeze",help="Explicitly freeze incumbent generations and future forecast watermark")
    commands.add_parser("truth-watch-check",help="Score eligible post-freeze outcomes; source and watch ledger read-only")
    commands.add_parser("truth-watch-record",help="Explicitly record an aggregate-only private research snapshot")
    commands.add_parser("truth-watch-history",help="Read saved snapshots without creating or changing files")
    commands.add_parser("challenger-freeze",help="Explicitly fit/freeze physical temperature challenger without changing GHOST")
    commands.add_parser("challenger-check",help="Read-only frozen challenger vs GHOST vs persistence outcomes")
    commands.add_parser("episode-challenge",help="Read-only, equal-event weighted challenger evaluation")
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
        elif args.command == "mission-next":
            result = mission_followup(args.source_db,args.architect_db,
                                      args.rows_per_block)
        elif args.command == "mission-conflicts":
            result = inspect_conflicts(historical_blocks(
                args.source_db,blocks=5,rows_per_block=args.rows_per_block))
        elif args.command == "mission-thermal":
            result = thermal_episode_challenge(historical_blocks(
                args.source_db,blocks=5,rows_per_block=args.rows_per_block))
        elif args.command == "mission-thermal-full":
            result = parked_thermal_research(args.source_db,max_rows=args.max_scan)
        elif args.command == "thermal-tournament":
            result = run_tournament(args.source_db,max_scan=args.max_scan)
        elif args.command == "shadow-freeze":
            result = freeze_shadow(args.source_db,args.shadow_db,
                                   max_scan=args.max_scan)
        elif args.command == "shadow-check":
            result = score_shadow(args.source_db,args.shadow_db,
                                  max_scan=args.max_scan)
        elif args.command == "shadow-status":
            result = shadow_status(args.shadow_db,args.source_db)
        elif args.command == "product-cycle":
            result = run_product_cycle(
                args.source_db,args.product_db,
                max_scan=args.max_scan,save=args.save,
                protected_paths=(args.research_db,args.architect_db,args.shadow_db))
        elif args.command == "truth-watch-freeze":
            result = freeze_watch(args.source_db,args.truth_watch_file)
        elif args.command == "truth-watch-check":
            result = check_watch(args.source_db,args.truth_watch_file)
        elif args.command == "truth-watch-record":
            result = record_history(args.source_db,args.truth_watch_file,args.truth_history_db)
        elif args.command == "truth-watch-history":
            result = read_history(args.truth_watch_file,args.truth_history_db)
        elif args.command == "challenger-freeze":
            result = freeze_challenger(args.source_db,args.truth_watch_file,args.challenger_file)
        elif args.command == "challenger-check":
            result = challenger_status(args.source_db,args.truth_watch_file,args.challenger_file)
        elif args.command == "episode-challenge":
            result = episode_challenge(args.source_db,args.truth_watch_file,args.challenger_file)
        elif args.command == "product-status":
            result = {"status":"LOCAL_RESEARCH_ONLY",
                      "runs":ProductLedger(args.product_db).read_recent(30),
                      "production_changes":False,"network_uploads":False}
        else:
            result = network_status()
    except (SourceUnavailable, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
