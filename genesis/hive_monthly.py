"""Strict aggregate evidence payloads for real, explicit-consent Hive contribution.

NO GPS, VIN, routes, drive times, per-event rows, user-defined key names,
model weights, raw errors or labels. Month-level sum/count ONLY.
This is pseudonymous authenticated transport, NOT anonymous or federated.
"""
from __future__ import annotations
import math
import re

SCHEMA="ghost-hive-monthly-v1"
METRIC="ghost-battery-temp-forecast-mae-v1"
PERIOD=re.compile(r"^20[2-9]\d-(0[1-9]|1[0-2])$")
KEYS=frozenset(("schema","metric","month","scored_predictions","total_abs_error_c","source"))
MIN_SCORES=25
MAX_SCORES=1000000
MAX_ERROR_C=30.0
MAX_BODY=350

class AggregateError(ValueError): pass

def validate_aggregate(obj:object)->dict:
    if not isinstance(obj,dict) or set(obj)!=KEYS:
        raise AggregateError("Unexpected aggregate fields")
    if obj["schema"]!=SCHEMA or obj["metric"]!=METRIC:
        raise AggregateError("Unsupported research schema")
    if obj["source"]!="ghost_prediction_audit":
        raise AggregateError("Unverified source type")
    if type(obj["month"]) is not str or not PERIOD.fullmatch(obj["month"]):
        raise AggregateError("Expected a UTC month, never a timestamp")
    n=obj["scored_predictions"]
    if type(n) is not int or not MIN_SCORES<=n<=MAX_SCORES:
        raise AggregateError("Not enough resolved forecasts, or count exceeds limit")
    err=obj["total_abs_error_c"]
    if type(err) not in (int,float) or not math.isfinite(float(err)):
        raise AggregateError("Invalid error sum")
    # Strict fixed precision: discourages encoding secret bits in decimals.
    value=round(float(err),2)
    if not 0<=value<=MAX_ERROR_C*n or abs(value-float(err))>0.000001:
        raise AggregateError("Error sum out of range or excessive precision")
    return {"schema":SCHEMA,"metric":METRIC,"month":obj["month"],
            "scored_predictions":n,"total_abs_error_c":value,
            "source":"ghost_prediction_audit"}
