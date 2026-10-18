"""Opt-in read-only GENESIS workspace, separate from the Classic dashboard."""
from __future__ import annotations

from flask import Blueprint, jsonify, make_response, render_template
from . import config
from .cli import overview

blueprint = Blueprint("ghost_genesis", __name__, template_folder="web")

@blueprint.get("/genesis")
def genesis_home():
    response = make_response(render_template("genesis_dashboard.html"))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@blueprint.get("/api/genesis/overview")
def genesis_overview():
    response = jsonify(overview(config.research_db()))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
