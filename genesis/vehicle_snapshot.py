"""Read-only, deliberately narrow local EV overview for a Ghost/Tessie-like UI.

No VIN, car ID, GPS, addresses, routes or raw JSON; all values are rounded.
Never send this endpoint's data to Hive. The UI is reachable only through
the independent loopback/SSH GENESIS preview.
"""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from .coverage import classify_regime
from .source import SourceUnavailable

FIELDS=("battery_level","battery_temp_c","outside_temp_c","inside_temp_c",
        "speed_kmh","charger_power_kw","charge_input_kw",
        "pack_power_kw","preconditioning")
def snapshot(source_db: Path,*, now: float|None=None)->dict:
    path=Path(source_db).expanduser().resolve()
    unavailable={"available":False,"state":"NO_DATA",
                 "read_only":True,"data_scope":"LOCAL_DEVICE_ONLY"}
    if not path.is_file():
        return unavailable
    uri="file:"+quote(str(path),safe="/")+"?mode=ro"
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=2)) as con:
            con.execute("PRAGMA query_only=ON")
            names={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
            if "ts" not in names:
                return unavailable
            if "car_id" in names:
                if con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]>1:
                    return unavailable
            selected=[k for k in FIELDS if k in names]
            if not selected:
                return unavailable
            columns=", ".join(['"ts"']+['"'+k+'"' for k in selected])
            values=con.execute(f"SELECT {columns} FROM telemetry ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return unavailable
    if values is None:
        return unavailable
    try:
        timestamp=float(values[0])
    except (ValueError,TypeError,OverflowError):
        return unavailable
    if not math.isfinite(timestamp):
        return unavailable
    point={}
    for name,value in zip(selected,values[1:]):
        try:
            f=float(value)
            point[name]=f if math.isfinite(f) else None
        except (TypeError,ValueError,OverflowError):
            point[name]=None
    current=time.time() if now is None else float(now)
    age=max(0.,current-timestamp)
    stale=age>300
    soc=point.get("battery_level")
    def temp(field):
        c=point.get(field)
        return round(c*1.8+32,1) if c is not None and -70<c<100 else None
    def round_safe(value,minimum,maximum,decimals=1):
        return round(value,decimals) if value is not None and minimum<=value<=maximum else None
    motion=point.get("speed_kmh")
    activity=classify_regime(point)
    # "PARKED_OR_OTHER" is NOT verified parking. Never promise real-time
    # battery/charge state from stale telemetry.
    return {
        "available":True,"fresh":not stale,
        "age_minutes":round(age/60,1),
        "state":activity if not stale else "STALE",
        "soc_percent":round_safe(soc,0,100,0),
        "pack_temp_f":temp("battery_temp_c"),
        "outside_temp_f":temp("outside_temp_c"),
        "cabin_temp_f":temp("inside_temp_c"),
        "speed_mph":round_safe(motion/1.609344 if motion is not None else None,0,200),
        "charger_kw":round_safe(point.get("charger_power_kw"),-5,350),
        "pack_kw":round_safe(point.get("pack_power_kw"),-500,500),
        "preconditioning_signal":(
            None if point.get("preconditioning") is None
            else bool(point["preconditioning"]>=.5)),
        "read_only":True,"data_scope":"LOCAL_DEVICE_ONLY",
        "note":"Inferred, last-observed sensor state. Some charging fields may be stale or contradictory.",
    }
