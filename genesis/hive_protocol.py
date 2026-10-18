"""GENESIS Hive v0 transport schema.

This is a conservative aggregate *transport protocol*, not cryptographic
secure aggregation, anonymity or differential privacy. Individual
contributions are visible to the private server operator. Do not publish
a fleet statistic with fewer than 25 independent registered participants.
"""
from __future__ import annotations
import math
import re

SCHEMA="genesis-hive-aggregate-v1"
MIN_COHORT=25
METRIC="parked_thermal_persistence_mae_c"
PERIOD=re.compile(r"^20[2-9][0-9]-(0[1-9]|1[0-2])$")
FIELDS=frozenset({"schema","metric","period","episodes","mae_c","origin"})
MAX_BODY=1024


class ProtocolError(ValueError):
    pass


def validate(payload: object, *, allow_synthetic: bool = True) -> dict:
    if not isinstance(payload,dict) or set(payload)!=FIELDS:
        raise ProtocolError("Payload must use exactly the approved aggregate fields.")
    if payload["schema"]!=SCHEMA or payload["metric"]!=METRIC:
        raise ProtocolError("Unsupported aggregate metric or schema.")
    if not isinstance(payload["period"],str) or not PERIOD.fullmatch(payload["period"]):
        raise ProtocolError("Unsupported coarse reporting period.")
    if (type(payload["episodes"]) is not int
            or not 10<=payload["episodes"]<=10000):
        raise ProtocolError("Episode count outside privacy and quality boundaries.")
    if type(payload["mae_c"]) not in (float,int):
        raise ProtocolError("Error metric must be numeric.")
    metric=float(payload["mae_c"])
    if not math.isfinite(metric) or not 0.0<=metric<=20.0:
        raise ProtocolError("Nonfinite or implausible error.")
    origin=payload["origin"]
    if origin not in ("synthetic","qualified_post_freeze"):
        raise ProtocolError("Unsupported origin.")
    if origin=="synthetic" and not allow_synthetic:
        raise ProtocolError("Synthetic contributions are not allowed in this server.")
    return {
        "schema":SCHEMA,"metric":METRIC,"period":payload["period"],
        "episodes":payload["episodes"],"mae_c":round(metric,4),"origin":origin,
    }
