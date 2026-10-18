"""Real leave-one-out Hive monthly research comparison.

Only the six-field monthly-aggregate evidence is used. The authenticated
requester is excluded from every peer cohort, so a sole enrolled installation
cannot be its own 'fleet benchmark'. Small peer cohorts may include ONLY
installations that separately opted into public monthly disclosure in or before
that UTC month. Original nonpublic cohorts require >=10 OTHER reporters.
No per-member observations, identifiers, routes, VINs or tokens are returned.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import sqlite3


SCHEMA = "ghost-hive-independent-comparison-v1"
MIN_ORIGINAL_COHORT = 10
MAX_MONTHS = 12


def _mae_f(total_c: float | None, samples: int | None) -> float | None:
    if not samples or total_c is None:
        return None
    return round(1.8 * float(total_c) / int(samples), 2)


def compare(path: Path, member_id: int, *, now: datetime | None = None) -> dict:
    """Read-only, authenticated owner's same-UTC-month monthly MAE comparison."""
    if type(member_id) is not int or member_id <= 0:
        raise ValueError("Authenticated active participant ID required")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware evaluation time required")

    months = []
    year, month = now.astimezone(timezone.utc).year, now.astimezone(timezone.utc).month
    for _ in range(MAX_MONTHS):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    months.reverse()
    uri = "file:" + quote(str(Path(path).expanduser().resolve()), safe="/") + "?mode=ro"

    with closing(sqlite3.connect(uri, uri=True, timeout=4)) as con:
        con.execute("PRAGMA query_only=ON")
        rows = con.execute("""SELECT month,scored_predictions,total_abs_error_c
             FROM monthly_research WHERE participant=? AND month>=? AND month<=?""",
             (member_id, months[0], months[-1])).fetchall()
        self_scores = {r[0]: (r[1],r[2]) for r in rows}
        cols = {r[1] for r in con.execute("PRAGMA table_info(participants)")}
        consent_sql = (
            "p.public_monthly=1 AND p.public_monthly_since IS NOT NULL "
            "AND m.month>=p.public_monthly_since"
            if {"public_monthly","public_monthly_since"} <= cols else "0=1"
        )
        # Both peer sets are computed as aggregate SQL results, never
        # returned as distinct installation rows.
        peers = con.execute(f"""SELECT m.month,
              COUNT(*) AS all_nodes,
              SUM(m.scored_predictions) AS all_scored,
              SUM(m.total_abs_error_c) AS all_error,
              SUM(CASE WHEN {consent_sql} THEN 1 ELSE 0 END) AS public_nodes,
              SUM(CASE WHEN {consent_sql} THEN m.scored_predictions ELSE 0 END)
                    AS public_scored,
              SUM(CASE WHEN {consent_sql} THEN m.total_abs_error_c ELSE 0 END)
                    AS public_error
             FROM monthly_research m
             JOIN participants p ON p.id=m.participant
             WHERE p.enabled=1 AND m.participant<>?
                 AND m.month>=? AND m.month<=?
             GROUP BY m.month""", (member_id,months[0],months[-1])).fetchall()
    peer_scores = {r[0]: r[1:] for r in peers}
    results = []
    for month in months:
        own = self_scores.get(month)
        all_counts = peer_scores.get(month)
        self_n, self_error = own if own else (None, None)
        visibility = "NO_PUBLISHABLE_PEERS"
        peer_count = peer_n = peer_error = None
        if all_counts:
            all_nodes, all_n, all_err, pub_nodes, pub_n, pub_err = all_counts
            if int(all_nodes) >= MIN_ORIGINAL_COHORT and all_n:
                visibility = "QUALIFIED_PEER_COHORT"
                peer_count,peer_n,peer_error = int(all_nodes),int(all_n),float(all_err)
            elif pub_nodes and int(pub_nodes)>0 and pub_n:
                visibility = "EXPLICIT_PUBLIC_PEERS"
                peer_count,peer_n,peer_error = int(pub_nodes),int(pub_n),float(pub_err)
        own_mae = _mae_f(self_error,self_n)
        peer_mae = _mae_f(peer_error,peer_n)
        advantage = (round(peer_mae-own_mae,2)
                     if peer_mae is not None and own_mae is not None else None)
        results.append({
            "month":month,
            "self_predictions":int(self_n) if self_n is not None else None,
            "self_mae_f":own_mae,
            "peer_installations":peer_count,
            "peer_predictions":peer_n,
            "peer_mae_f":peer_mae,
            "self_advantage_f":advantage,
            "peer_visibility":visibility,
            "comparison_status":(
                "COMPARABLE" if advantage is not None
                else "NO_LOCAL_MONTHLY_REPORT" if own_mae is None
                else "AWAITING_PUBLISHABLE_PEERS"),
        })
    comparable = [r for r in results if r["comparison_status"]=="COMPARABLE"]
    latest = comparable[-1] if comparable else None
    has_self = any(r["self_mae_f"] is not None for r in results)
    return {
        "schema":SCHEMA,
        "scope":"AUTHENTICATED_INSTALLATION_ONLY",
        "status":("COMPARISON_AVAILABLE" if latest else
                  "AWAITING_PUBLISHABLE_PEERS" if has_self else
                  "AWAITING_LOCAL_MONTHLY_REPORT"),
        "latest_month":latest["month"] if latest else None,
        "latest":latest,
        "months":results,
        "self_excluded_from_peers":True,
        "peer_metric":"BATTERY_TEMP_MONTHLY_MAE_F",
        "source":"SELF_REPORTED_MONTHLY_AGGREGATES",
        "can_promote":False,
        "network_uploads":False,
        "limitations":[
            "Only enrolled reporting installations, not verified unique vehicles.",
            "Month-level MAE is not within-2F accuracy and does not adjust for fleet differences.",
            "Original private groups need ten OTHER reporting installations; smaller peer groups require separate public-monthly permission.",
            "The requesting installation is excluded from all peer calculations.",
            "Month-level aggregates do not establish matched operating conditions, driving routes, model quality or causality.",
            "No model promotion, retraining, vehicle commands or new telemetry upload.",
        ],
    }
