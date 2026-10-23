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

from flask import Flask,request,jsonify,abort,render_template
from .hive_analytics import cohort_dashboard,synthetic_demo
from .hive_monthly import validate_aggregate, AggregateError, MAX_BODY as REAL_MAX_BODY
from .hive_public import summary as public_summary
from .hive_peer_comparison import compare as compare_member
from .hive_models import validate_model_manifest, ModelMetadataError
from .hive_regions import validate_region_payload, RegionError, REGIONS

from werkzeug.serving import make_server
from .hive_protocol import validate,ProtocolError,MIN_COHORT,MAX_BODY,METRIC

SQL="""
CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  public_monthly INTEGER NOT NULL DEFAULT 0,
  public_monthly_since TEXT
);
CREATE TABLE IF NOT EXISTS contributions (
  participant INTEGER NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,
  origin TEXT NOT NULL, episodes INTEGER NOT NULL, mae_c REAL NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY(participant, period, metric, origin),
  FOREIGN KEY(participant) REFERENCES participants(id)
);
CREATE TABLE IF NOT EXISTS monthly_research(
 participant INTEGER NOT NULL, month TEXT NOT NULL,
 scored_predictions INTEGER NOT NULL, total_abs_error_c REAL NOT NULL,
 received_at INTEGER NOT NULL,
 PRIMARY KEY(participant,month),
 FOREIGN KEY(participant) REFERENCES participants(id)
);
CREATE TABLE IF NOT EXISTS region_consents(
 participant INTEGER PRIMARY KEY,
 region_code TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 public_listing INTEGER NOT NULL DEFAULT 0,
 changed_at INTEGER NOT NULL,
 FOREIGN KEY(participant) REFERENCES participants(id)
);
CREATE TABLE IF NOT EXISTS model_manifests(
 participant INTEGER NOT NULL, family TEXT NOT NULL,
 manifest_json TEXT NOT NULL, received_at INTEGER NOT NULL,
 PRIMARY KEY(participant,family),
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
        members={r[1] for r in con.execute("PRAGMA table_info(participants)")}
        if "public_monthly" not in members:
            # Older aggregate consent was for hidden small cohorts. Default PRIVATE.
            con.execute("ALTER TABLE participants ADD COLUMN public_monthly INTEGER NOT NULL DEFAULT 0")
        if "public_monthly_since" not in members:
            con.execute("ALTER TABLE participants ADD COLUMN public_monthly_since TEXT")
        columns={r[1] for r in con.execute("PRAGMA table_info(region_consents)")}
        if "public_listing" not in columns:
            # Existing broad-region choices remain nonpublic until reconsented.
            con.execute("ALTER TABLE region_consents ADD COLUMN public_listing INTEGER NOT NULL DEFAULT 0")
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
        row=con.execute("SELECT id,enabled FROM participants WHERE secret_hash=?",(digest,)).fetchone()
        if not row or not row[1]:
            return False
        con.execute("DELETE FROM contributions WHERE participant=?",(row[0],))
        con.execute("DELETE FROM monthly_research WHERE participant=?",(row[0],))
        con.execute("DELETE FROM model_manifests WHERE participant=?",(row[0],))
        con.execute("DELETE FROM region_consents WHERE participant=?",(row[0],))
        con.execute("UPDATE participants SET enabled=0 WHERE id=?",(row[0],))
        con.commit()
    return True


def create_app(path: Path) -> Flask:
    db=_private(path)
    initialize(db)
    app=Flask(__name__,template_folder="web")
    app.config["MAX_CONTENT_LENGTH"]=MAX_BODY

    @app.after_request
    def secure_headers(resp):
        resp.headers["Cache-Control"]="no-store"
        resp.headers["X-Content-Type-Options"]="nosniff"
        resp.headers["X-Frame-Options"]="DENY"
        resp.headers["Referrer-Policy"]="no-referrer"
        resp.headers["Content-Security-Policy"]=(
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'")
        return resp

    @app.get("/health")
    def health():
        return jsonify({"ok":True,"service":"GENESIS_HIVE",
                        "stage":"PRIVATE_COHORT_TRANSPORT_PREVIEW",
                        "cohort_gate":MIN_COHORT,
                        "secure_aggregation":False,
                        "differential_privacy":False})

    @app.get("/hive")
    def hive_dashboard():
        return render_template("hive_analytics.html")

    @app.get("/api/hive/analytics")
    def hive_analytics():
        origin=request.args.get("origin","synthetic")
        if origin not in ("synthetic","qualified_post_freeze"):
            return jsonify({"error":"UNSUPPORTED_COHORT_TYPE"}),400
        if request.args.get("demo")=="1":
            return jsonify(synthetic_demo())
        # This route is loopback-only, protected by the same SSH tunnel
        # boundary as the standalone development dashboard. The future
        # internet-facing dashboard MUST have proper per-user auth.
        return jsonify(cohort_dashboard(db,origin=origin))

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

    @app.delete("/v1/enrollment")
    def delete_enrollment():
        # A member can revoke its OWN token without admin intervention.
        # No client IP, VIN, GPS or other identifier enters the database.
        user=authenticate()
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("DELETE FROM contributions WHERE participant=?",(user,))
            con.execute("DELETE FROM monthly_research WHERE participant=?",(user,))
            con.execute("DELETE FROM model_manifests WHERE participant=?",(user,))
            con.execute("DELETE FROM region_consents WHERE participant=?",(user,))
            con.execute("UPDATE participants SET enabled=0 WHERE id=?",(user,))
            con.commit()
        return jsonify({"revoked":True,"contributions_erased":True}),200

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
        # Phase 1 accepts synthetic data only. The transport schema may
        # describe future qualified research, but this server has NO means
        # to attest its provenance, so it must fail closed.
        if metric["origin"]!="synthetic":
            return jsonify({"error":"REAL_CONTRIBUTIONS_NOT_ENABLED"}),403
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

    @app.put("/v1/region")
    def set_broad_region():
        """Separately opted-in continent-scale region; NEVER infer location."""
        user=authenticate()
        if request.mimetype!="application/json":
            abort(415)
        if request.content_length is not None and request.content_length>96:
            abort(413)
        try:
            selected=validate_region_payload(request.get_json(silent=True))
        except RegionError:
            return jsonify({"error":"INVALID_BROAD_REGION"}),400
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("""INSERT INTO region_consents(
                participant,region_code,enabled,changed_at) VALUES(?,?,1,?)
                ON CONFLICT(participant) DO UPDATE SET
                region_code=excluded.region_code,enabled=1,
                public_listing=0,changed_at=excluded.changed_at""",
                (user,selected["region_code"],int(time.time())))
            con.commit()
        return jsonify({"accepted":True,"regional_sharing":"OPTED_IN",
                        "region_code":selected["region_code"],
                        "exact_location_collected":False}),202

    @app.put("/v1/monthly-publication")
    def publish_small_monthly_cohorts():
        """Separately opt in to publication of one's aggregate MAE from 1 member."""
        user=authenticate()
        if request.mimetype!="application/json":abort(415)
        if request.content_length is None or request.content_length>160:abort(413)
        body=request.get_json(silent=True)
        if (not isinstance(body,dict)
            or set(body)!={"schema","acknowledge_public_from_one"}
            or body.get("schema")!="ghost-hive-monthly-public-v1"
            or body.get("acknowledge_public_from_one") is not True):
            return jsonify({"error":"SMALL_MONTHLY_PUBLIC_CONSENT_REQUIRED"}),400
        with closing(sqlite3.connect(db,timeout=4)) as con:
            month=time.strftime("%Y-%m",time.gmtime())
            changed=con.execute("""UPDATE participants SET public_monthly=1,
                public_monthly_since=COALESCE(public_monthly_since,?)
                WHERE id=? AND enabled=1""",(month,user))
            if changed.rowcount!=1:
                return jsonify({"error":"ACTIVE_HIVE_ENROLLMENT_REQUIRED"}),409
            con.commit()
        return jsonify({"accepted":True,"public_monthly":True,
                        "data_scope":"MONTHLY_AGGREGATE_ONLY",
                        "one_reporter_visibility":True}),202

    @app.delete("/v1/monthly-publication")
    def hide_small_monthly_cohorts():
        user=authenticate()
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("UPDATE participants SET public_monthly=0, public_monthly_since=NULL WHERE id=?",(user,))
            con.commit()
        return jsonify({"public_monthly":False,"deleted":True}),200

    @app.put("/v1/region-publication")
    def publish_region_one_member():
        """Explicit new consent to list a coarse world region from one reporter."""
        user=authenticate()
        if request.mimetype!="application/json":abort(415)
        if request.content_length is None or request.content_length>160:abort(413)
        body=request.get_json(silent=True)
        if (not isinstance(body,dict)
            or set(body)!={"schema","acknowledge_single_reporter_public"}
            or body["schema"]!="ghost-hive-region-public-v1"
            or body["acknowledge_single_reporter_public"] is not True):
            return jsonify({"error":"SINGLE_REPORTER_PUBLIC_CONSENT_REQUIRED"}),400
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            updated=con.execute("""UPDATE region_consents
                SET public_listing=1, changed_at=?
                WHERE participant=? AND enabled=1""",
                (int(time.time()),user))
            if updated.rowcount!=1:
                return jsonify({"error":"SELECT_BROAD_REGION_FIRST"}),409
            con.commit()
        return jsonify({"accepted":True,"public_listing":True,
                        "regional_scope":"VOLUNTARY_BROAD_REGION_ONLY",
                        "one_member_visibility":True}),202

    @app.delete("/v1/region-publication")
    def hide_public_region():
        user=authenticate()
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("UPDATE region_consents SET public_listing=0, changed_at=? WHERE participant=?",
                        (int(time.time()),user))
            con.commit()
        return jsonify({"public_listing":False,"deleted":True}),200

    @app.delete("/v1/region")
    def clear_broad_region():
        user=authenticate()
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("DELETE FROM region_consents WHERE participant=?",(user,))
            con.commit()
        return jsonify({"regional_sharing":"OFF","deleted":True})

    @app.post("/v1/monthly-research")
    def monthly_research():
        participant=authenticate()
        if request.mimetype!="application/json":
            abort(415)
        # A real submission is accepted only after the client has presented
        # informed local consent, and the server has validated all fields.
        # The coordinator cannot independently prove data provenance.
        if (request.content_length is not None
                and request.content_length>REAL_MAX_BODY):
            abort(413)
        try:
            sample=validate_aggregate(request.get_json(silent=True))
        except AggregateError:
            return jsonify({"error":"INVALID_MONTHLY_AGGREGATE"}),400
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("""INSERT INTO monthly_research(
                participant,month,scored_predictions,total_abs_error_c,received_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(participant,month) DO UPDATE SET
                  scored_predictions=excluded.scored_predictions,
                  total_abs_error_c=excluded.total_abs_error_c,
                  received_at=excluded.received_at
            """,(participant,sample["month"],sample["scored_predictions"],
                 sample["total_abs_error_c"],int(time.time())))
            con.commit()
        return jsonify({"accepted":True,"mode":"SELF_REPORTED_COARSE_AGGREGATE",
                        "scope":"ONE_UTC_MONTH","no_model_promotion":True}),202

    @app.post("/v1/model-manifests")
    def model_manifests():
        """Quarantine only typed research metadata; no model binaries, ever."""
        participant=authenticate()
        if request.mimetype!="application/json":
            abort(415)
        if request.content_length is not None and request.content_length>600:
            abort(413)
        try:
            manifest=validate_model_manifest(request.get_json(silent=True))
        except ModelMetadataError:
            return jsonify({"error":"INVALID_MODEL_METADATA"}),400
        with closing(sqlite3.connect(db,timeout=4)) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("""INSERT INTO model_manifests(
               participant,family,manifest_json,received_at) VALUES(?,?,?,?)
               ON CONFLICT(participant,family) DO UPDATE SET
               manifest_json=excluded.manifest_json,
               received_at=excluded.received_at""",
               (participant,manifest["family"],
                json.dumps(manifest,sort_keys=True),int(time.time())))
            con.commit()
        return jsonify({"accepted":True,"status":"QUARANTINED_METADATA_ONLY",
                        "weights_uploaded":False,"production_promotion":False}),202

    @app.get("/v1/member-comparison")
    def member_comparison():
        # Bearer-authenticated private response, never part of public-network.
        member=authenticate()
        return jsonify(compare_member(db,member))

    @app.get("/v1/public-network")
    def public_network():
        return jsonify(public_summary(db))

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
    enrollment=sp.add_parser("enroll")
    enrollment.add_argument("--token-file",type=Path,
        help="Write token to a newly created private 0600 file, without printing it")
    sp.add_parser("init")
    revoke_p=sp.add_parser("revoke")
    revoke_p.add_argument("--token-file",type=Path,required=True)
    args=p.parse_args(argv)
    if args.command=="init":
        initialize(args.db); print("HIVE_PRIVATE_DATABASE_INITIALIZED");return 0
    if args.command=="enroll":
        path=args.token_file.expanduser().absolute() if args.token_file else None
        if path is not None:
            if path.exists() or path.is_symlink():
                p.error("Token file already exists; refusing overwrite")
            if not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
                p.error("Token directory must exist with private 0700 permissions")
        token=enroll(args.db)
        if path is not None:
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,"w") as out:out.write(token+"\n")
            except Exception:
                revoke(args.db,token)
                raise
            print("PRIVATE_ENROLLMENT_TOKEN_FILE:",path)
        else:
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
