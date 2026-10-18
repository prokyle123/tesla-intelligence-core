"""Isolated opt-in GENESIS Hive server.

Loopback-only *development* service; never bind to external interfaces.
For a real multi-node deployment use a reviewed authenticated TLS
reverse proxy, IP/log privacy policy, backups, abuse controls, and
private server storage. Server sees each participant's aggregate:
NOT differential privacy, secure aggregation, or anonymization.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from flask import Flask,request,jsonify,abort
from werkzeug.serving import make_server
from .hive_protocol import validate,ProtocolError,MIN_COHORT,MAX_BODY,METRIC

SQL="""
CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contributions (
  participant INTEGER NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,
  origin TEXT NOT NULL, episodes INTEGER NOT NULL, mae_c REAL NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY(participant, period, metric, origin),
  FOREIGN KEY(participant) REFERENCES participants(id)
);
"""


def _private(path: Path) -> Path:
    p=Path(path).expanduser().absolute()
    if p.is_symlink():
        raise ValueError("Symlink Hive database not allowed.")
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.parent.stat().st_mode & 0o077:
        raise ValueError("Hive directory must have 0700 private permissions.")
    if p.exists() and p.stat().st_mode & 0o077:
        raise ValueError("Hive database must have 0600 permissions.")
    return p


def initialize(path: Path):
    p=_private(path)
    with closing(sqlite3.connect(p)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(SQL)
        con.commit()
    p.chmod(0o600)


def enroll(path: Path) -> str:
    """Administrator executes locally; plaintext credential shown once."""
    initialize(path)
    token=secrets.token_urlsafe(36)
    digest=hashlib.sha256(token.encode()).hexdigest()
    with closing(sqlite3.connect(path)) as con:
        con.execute("INSERT INTO participants(secret_hash,created_at) VALUES(?,?)",
                    (digest,int(time.time())))
        con.commit()
    return token


def revoke(path: Path, token: str) -> bool:
    """Local operator can revoke a participant and erase its contributions."""
    digest=hashlib.sha256(token.encode()).hexdigest()
    with closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        row=con.execute("SELECT id FROM participants WHERE secret_hash=?",(digest,)).fetchone()
        if not row:
            return False
        con.execute("DELETE FROM contributions WHERE participant=?",(row[0],))
        con.execute("UPDATE participants SET enabled=0 WHERE id=?",(row[0],))
        con.commit()
    return True


def create_app(path: Path) -> Flask:
    db=_private(path)
    initialize(db)
    app=Flask("genesis-hive")
    app.config["MAX_CONTENT_LENGTH"]=MAX_BODY

    @app.after_request
    def secure_headers(resp):
        resp.headers["Cache-Control"]="no-store"
        resp.headers["X-Content-Type-Options"]="nosniff"
        resp.headers["X-Frame-Options"]="DENY"
        return resp

    @app.get("/health")
    def health():
        return jsonify({"ok":True,"service":"GENESIS_HIVE",
                        "stage":"PRIVATE_COHORT_TRANSPORT_PREVIEW",
                        "cohort_gate":MIN_COHORT,
                        "secure_aggregation":False,
                        "differential_privacy":False})

    def authenticate():
        token=request.headers.get("Authorization","")
        if not token.startswith("Bearer "):
            abort(401)
        secret=token[7:]
        if len(secret)<32 or len(secret)>200:
            abort(401)
        digest=hashlib.sha256(secret.encode()).hexdigest()
        with closing(sqlite3.connect(db)) as con:
            row=con.execute("SELECT id,enabled FROM participants WHERE secret_hash=?",
                            (digest,)).fetchone()
        if row is None or row[1]!=1:
            abort(401)
        return row[0]

    @app.post("/v1/contributions")
    def contribute():
        user=authenticate()
        if request.mimetype!="application/json":
            abort(415)
        payload=request.get_json(silent=True)
        try:
            metric=validate(payload)
        except ProtocolError:
            return jsonify({"error":"INVALID_AGGREGATE"}),400
        # The service stores only allowlisted statistics; uniqueness per
        # registered participant and period prevents duplicate weighting.
        with closing(sqlite3.connect(db,timeout=3)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("""INSERT INTO contributions(
                participant,period,metric,origin,episodes,mae_c,received_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(participant,period,metric,origin) DO UPDATE SET
                episodes=excluded.episodes,
                mae_c=excluded.mae_c,
                received_at=excluded.received_at""",
                (user,metric["period"],metric["metric"],metric["origin"],
                 metric["episodes"],metric["mae_c"],int(time.time())))
            con.commit()
        return jsonify({"accepted":True,"stored":"AGGREGATE_ONLY",
                        "origin":metric["origin"],
                        "publishable":False}),202

    @app.get("/v1/cohorts/<period>")
    def cohort(period):
        # Read-only cohort summaries, but not publicly released before
        # the minimum number of distinct participants.
        if not isinstance(period,str) or len(period)!=7:
            abort(404)
        origin=request.args.get("origin","synthetic")
        if origin not in ("synthetic","qualified_post_freeze"):
            abort(400)
        # Require authentication even for gated cohort counts.
        authenticate()
        with closing(sqlite3.connect(db)) as con:
            count,total,weighted=con.execute("""
              SELECT COUNT(DISTINCT participant),SUM(episodes),
                     SUM(mae_c*episodes) FROM contributions
              WHERE period=? AND origin=? AND metric=? AND participant IN
              (SELECT id FROM participants WHERE enabled=1)
              """,(period,origin,METRIC)).fetchone()
        if count<MIN_COHORT:
            return jsonify({"status":"COHORT_WITHHELD",
                            "minimum_participants":MIN_COHORT,
                            "aggregate":None})
        return jsonify({
            "status":"RESEARCH_COHORT_AVAILABLE",
            "minimum_participants":MIN_COHORT,
            "participants":count,
            "episodes":total,
            "mean_mae_c":round(weighted/total,4) if total else None,
            "origin":origin,
            "caution":"Private server sees individual aggregate contributions; not secure aggregation or differential privacy.",
        })
    return app


def main(argv=None):
    p=argparse.ArgumentParser(description="Private loopback GENESIS Hive server")
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--port",type=int,default=8778)
    sp=p.add_subparsers(dest="command",required=True)
    sp.add_parser("serve")
    sp.add_parser("enroll")
    sp.add_parser("init")
    revoke_p=sp.add_parser("revoke")
    revoke_p.add_argument("--token-file",type=Path,required=True)
    args=p.parse_args(argv)
    if args.command=="init":
        initialize(args.db); print("HIVE_PRIVATE_DATABASE_INITIALIZED");return 0
    if args.command=="enroll":
        token=enroll(args.db)
        print("PARTICIPANT_TOKEN_SHOW_ONCE:",token)
        print("Keep the token in a 0600 file. Never paste it into a public chat.")
        return 0
    if args.command=="revoke":
        file=args.token_file.expanduser()
        if file.stat().st_mode & 0o077:
            p.error("Token file must have private permissions.")
        token=file.read_text().strip()
        print("PARTICIPANT_REVOKED_AND_ERASED" if revoke(args.db,token)
              else "NO_MATCHING_PARTICIPANT")
        return 0
    if not 1024<=args.port<=65535:p.error("Port outside allowed range.")
    app=create_app(args.db)
    # No automatic LAN or Tailscale exposure.
    srv=make_server("127.0.0.1",args.port,app,threaded=True)
    print(f"HIVE PRIVATE SERVER: http://127.0.0.1:{args.port}/health",flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally: srv.server_close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
