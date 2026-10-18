"""Hivemind *offline design harness*: absolutely no client transport.

This is NOT federated learning, not secure aggregation and not differential
privacy. Do not use the demo output for public fleet statistics. Networked
training will require a separately reviewed protocol and privacy threat model.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import os

MIN_COHORT = 25

class ParticipationMode(str, Enum):
    LOCAL_ONLY = "off"
    RECEIVE_ONLY = "receive"
    CONTRIBUTE_REQUESTED = "contribute"

def participation_mode() -> ParticipationMode:
    supplied = os.environ.get("GHOST_HIVEMIND_MODE", "off").strip().lower()
    try:
        return ParticipationMode(supplied)
    except ValueError:
        return ParticipationMode.LOCAL_ONLY

def network_status() -> dict:
    mode = participation_mode()
    return {
        "mode": mode.value,
        "network_enabled": False,
        "outbound_uploads": False,
        "global_models_enabled": False,
        "fleet_service": "NOT_IMPLEMENTED",
        "reason": "No Hivemind network transport is installed; opt-in cannot override this safety gate.",
    }

class PrivacyGate(RuntimeError):
    pass

@dataclass(frozen=True)
class SyntheticClientMetric:
    """Synthetic round testing ONLY: no vehicle/driver identifiers."""
    count: int
    loss_sum: float

def simulate_cohort(metrics: list[SyntheticClientMetric]) -> dict:
    """Demonstrate only minimum cohort and numerical guards, never publish it."""
    if len(metrics) < MIN_COHORT:
        raise PrivacyGate("Cohort too small for a fleet result.")
    if any(m.count < 1 or not math.isfinite(m.loss_sum) or m.loss_sum < 0
           or m.count > 100000 for m in metrics):
        raise PrivacyGate("Invalid synthetic metric.")
    rows = sum(m.count for m in metrics)
    return {
        "simulation": True,
        "publishable": False,
        "participant_count": len(metrics),
        "synthetic_mean_loss": round(sum(m.loss_sum for m in metrics) / rows, 6),
        "warning": "NOT privacy-preserving. No real telemetry or client updates may be used.",
    }
