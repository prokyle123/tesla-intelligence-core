"""Read-only Starlink local dish telemetry for GHOST.

Uses the Starlink terminal's local gRPC reflection endpoint:
  192.168.100.1:9200

Only get_history is requested. No control RPCs are implemented.
"""
from __future__ import annotations

import math
import threading
import time

_LOCK = threading.Lock()
_REFLECTOR = None
_STUB_CLASS = None
_REQUEST_CLASS = None

TARGET = "192.168.100.1:9200"
TIMEOUT_S = 3.0

def _classes(channel):
    global _REFLECTOR, _STUB_CLASS, _REQUEST_CLASS
    if _STUB_CLASS is not None and _REQUEST_CLASS is not None:
        return _STUB_CLASS, _REQUEST_CLASS

    import grpc
    from yagrc import reflector

    r = reflector.GrpcReflectionClient()
    r.load_protocols(channel, symbols=["SpaceX.API.Device.Device"])
    _REFLECTOR = r
    _STUB_CLASS = r.service_stub_class("SpaceX.API.Device.Device")
    _REQUEST_CLASS = r.message_class("SpaceX.API.Device.Request")
    return _STUB_CLASS, _REQUEST_CLASS

def _latest_ring_value(values, current):
    vals = list(values or [])
    if not vals:
        return None
    try:
        cur = int(current)
    except Exception:
        cur = 0

    # Starlink history is a ring buffer. "current" is the counter for the
    # next sample, so current-1 points at the newest sample after wrap.
    if cur > 0:
        idx = (cur - 1) % len(vals)
    else:
        idx = len(vals) - 1

    try:
        value = float(vals[idx])
    except Exception:
        return None
    return value if math.isfinite(value) else None

def read_power():
    """Return a compact read-only result from dish_get_history."""
    started = time.monotonic()
    with _LOCK:
        try:
            import grpc

            with grpc.insecure_channel(TARGET) as channel:
                stub_class, request_class = _classes(channel)
                stub = stub_class(channel)
                response = stub.Handle(
                    request_class(get_history={}),
                    timeout=TIMEOUT_S,
                )
                history = response.dish_get_history

                power_w = _latest_ring_value(
                    getattr(history, "power_in", []),
                    getattr(history, "current", 0),
                )

                return {
                    "ok": power_w is not None,
                    "power_w": None if power_w is None else round(power_w, 1),
                    "source": "dish_get_history.power_in",
                    "query_ms": round((time.monotonic() - started) * 1000.0, 1),
                    "error": None if power_w is not None else "power_in unavailable",
                }
        except ImportError as exc:
            return {
                "ok": False,
                "power_w": None,
                "source": "dish_get_history.power_in",
                "query_ms": round((time.monotonic() - started) * 1000.0, 1),
                "error": f"Starlink gRPC runtime missing: {exc}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "power_w": None,
                "source": "dish_get_history.power_in",
                "query_ms": round((time.monotonic() - started) * 1000.0, 1),
                "error": f"{type(exc).__name__}: {exc}",
            }
