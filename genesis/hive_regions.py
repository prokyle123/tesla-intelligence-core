"""Hive opt-in broad-region research, never GPS, IP lookup or exact routes.

Members choose a categorical world macro-region manually. Server publishes
regional hotspots ONLY when at least 10 active reporting enrollments
independently opted into that category. Positions are decorative fixed
centroids of huge world regions, not positions derived from vehicles.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

MIN_REGION_MEMBERS=10
REGION_SCHEMA="ghost-hive-region-v1"
# These markers are intentionally wide macro-regions, not states or cities.
# x/y describe approximate placement in the SVG base map with viewBox 760x330.
REGIONS={
    "NORTH_AMERICA_WEST":("Western North America",128,111),
    "NORTH_AMERICA_EAST":("Eastern North America",180,110),
    "SOUTH_AMERICA":("South America",166,235),
    "EUROPE":("Europe",371,99),
    "AFRICA":("Africa",397,189),
    "ASIA":("Asia",520,118),
    "OCEANIA":("Oceania",653,260),
}
class RegionError(ValueError):pass

def validate_region_payload(value:Any)->dict:
    if not isinstance(value,dict) or set(value)!={"schema","region_code"}:
        raise RegionError("Unexpected location data fields")
    if value["schema"]!=REGION_SCHEMA or type(value["region_code"]) is not str or value["region_code"] not in REGIONS:
        raise RegionError("Unsupported broad region")
    return {"schema":REGION_SCHEMA,"region_code":value["region_code"]}

def public_regions(con,threshold:int=MIN_REGION_MEMBERS)->list[dict]:
    if threshold<MIN_REGION_MEMBERS:
        raise RegionError("Unacceptable regional privacy threshold")
    existing={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "region_consents" not in existing:
        return []
    rows=con.execute("""
      SELECT r.region_code,COUNT(DISTINCT r.participant) AS contributors
      FROM region_consents r JOIN participants p ON p.id=r.participant
      WHERE p.enabled=1 AND r.enabled=1
        AND EXISTS (
          SELECT 1 FROM monthly_research m WHERE m.participant=r.participant
        )
      GROUP BY r.region_code
    """).fetchall()
    out=[]
    for key,count in rows:
        if key not in REGIONS or count<threshold:continue
        label,x,y=REGIONS[key]
        out.append({"code":key,"label":label,"x":x,"y":y,
                    "reporting_nodes":int(count)})
    return sorted(out,key=lambda v:(-v["reporting_nodes"],v["code"]))
