"""Read-only GENESIS product workspace; never mutates research from HTTP.

Existing GHOST can register the blueprint behind its own authentication
and routing policy. Standalone preview uses a loopback-only socket.
"""
from __future__ import annotations

from pathlib import Path
from flask import Blueprint, current_app, jsonify, make_response, render_template

from . import config
from .cli import overview
from .product_core import ProductLedger
from .vehicle_snapshot import snapshot
from .prediction_truth import prediction_truth
from .thermal_context import thermal_context
from .paired_baseline import paired_baseline
from .prospective_truth_watch import check_watch
from .truth_watch_history import read_history
from .hive_transfer import status as hive_client_status

blueprint = Blueprint("ghost_genesis", __name__, template_folder="web")


def _private_data_dir() -> Path:
    value=current_app.config.get("GENESIS_DATA_DIR")
    return Path(value).expanduser().resolve() if value else config.data_dir().resolve()


def _headers(response):
    response.headers["Cache-Control"]="no-store"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Content-Security-Policy"]=(
        "default-src 'self'; script-src 'self' 'unsafe-inline';"
        " style-src 'self' 'unsafe-inline'; object-src 'none';"
        " base-uri 'none'; frame-ancestors 'none'; connect-src 'self'")
    return response


@blueprint.get("/genesis")
def genesis_home():
    return _headers(make_response(render_template("genesis_dashboard.html")))


@blueprint.get("/api/genesis/overview")
def genesis_overview():
    root=_private_data_dir()
    # No database creation: all stores open in mode=ro or return [].
    data=overview(root/"research.sqlite3",data_dir=root)
    data["product_runs"]=ProductLedger(root/"product.sqlite3").read_recent(20)
    data["product_version"]="0.6.0-preview"
    data["product_state"]="LOCAL_RESEARCH_ONLY"
    data["production_changes"]=False
    return _headers(jsonify(data))


@blueprint.get("/api/genesis/vehicle")
def genesis_vehicle():
    # Explicitly local only. This route is never registered by the Hive
    # coordinator, which receives only allowlisted aggregates.
    source=current_app.config.get("GENESIS_SOURCE_DB") or str(config.source_db())
    return _headers(jsonify(snapshot(Path(source))))


@blueprint.get("/api/genesis/prediction-quality")
def genesis_prediction_quality():
    # Read-only on the production GHOST database. Never shares event rows.
    source=current_app.config.get("GENESIS_SOURCE_DB") or str(config.source_db())
    return _headers(jsonify(prediction_truth(Path(source))))


@blueprint.get("/api/genesis/thermal-context")
def genesis_thermal_context():
    # Strictly read-only source telemetry context for model truth investigation.
    source=current_app.config.get("GENESIS_SOURCE_DB") or str(config.source_db())
    return _headers(jsonify(thermal_context(Path(source))))


@blueprint.get("/api/genesis/paired-baseline")
def genesis_paired_baseline():
    # Every scored challenger and persistence score uses the same observed outcome.
    source=current_app.config.get("GENESIS_SOURCE_DB") or str(config.source_db())
    return _headers(jsonify(paired_baseline(Path(source))))


@blueprint.get("/api/genesis/prospective-watch")
def genesis_prospective_watch():
    # Status endpoint never freezes anything. A manual CLI action creates
    # an immutable private file before any future evidence is eligible.
    source=current_app.config.get("GENESIS_SOURCE_DB") or str(config.source_db())
    frozen=_private_data_dir() / "prospective-truth-watch.json"
    history=_private_data_dir() / "prospective-truth-history.sqlite3"
    try:
        report=check_watch(Path(source),frozen)
        report["history"]=read_history(frozen,history,limit=14)
    except (ValueError,OSError) as exc:
        report={"status":"WATCH_UNAVAILABLE","scope":"LOCAL_GHOST_ONLY",
                "reason":type(exc).__name__,"models":[],
                "production_changes":False,"network_uploads":False,
                "can_promote":False,"automatic_execution":False}
    return _headers(jsonify(report))


@blueprint.get("/api/genesis/hive")
def genesis_hive_client():
    root=_private_data_dir()
    return _headers(jsonify(hive_client_status(root/"hive-client")))


@blueprint.get("/api/genesis/health")
def genesis_health():
    root=_private_data_dir()
    return _headers(jsonify({
        "ok":True,
        "component":"GENESIS workspace",
        "version":"0.6.0-preview",
        "network":"LOCAL_ONLY",
        "data_available":(root/"product.sqlite3").is_file(),
        "research_only":True,
        "production_changes":False,
    }))
