"""Synthetic-only multi-node learning simulator.

No real user telemetry is accepted. This is NOT secure aggregation, differential
privacy, a working fleet client or a basis for public fleet statistics.
"""
from __future__ import annotations

import math
import random
from .hivemind import MIN_COHORT, PrivacyGate

def _gradient(data: list[tuple[float, float]], weight: float, bias: float) -> tuple[float, float]:
    n = len(data)
    dw = sum(2.0 * (weight * x + bias - y) * x for x, y in data) / n
    db = sum(2.0 * (weight * x + bias - y) for x, y in data) / n
    # Local gradient clipping illustrates bounding, NOT differential privacy.
    norm = math.hypot(dw, db)
    if norm > 2:
        dw, db = dw * 2 / norm, db * 2 / norm
    return dw, db

def _score(groups: list[list[tuple[float, float]]], w: float, b: float) -> float:
    total = sum(len(g) for g in groups)
    return sum(abs(w*x+b-y) for g in groups for x,y in g) / total

def simulate_fleet(*, vehicles: int = 32, rounds: int = 30, seed: int = 17) -> dict:
    """Run a reproducible offline toy-fleet learning round, no external I/O."""
    if not MIN_COHORT <= vehicles <= 200:
        raise PrivacyGate("Synthetic fleet must meet minimum cohort and size cap.")
    if not 1 <= rounds <= 100:
        raise ValueError("Rounds out of supported offline bounds.")
    rng = random.Random(seed)
    training = []
    testing = []
    for _ in range(vehicles):
        # This is deliberately fictional, with NO user-provided input data.
        slope = 1.6 + rng.uniform(-.12, .12)
        intercept = .3 + rng.uniform(-.08, .08)
        train = [(rng.uniform(-1,1), 0.0) for _ in range(60)]
        test = [(rng.uniform(-1,1), 0.0) for _ in range(20)]
        training.append([(x, slope*x+intercept+rng.gauss(0,.04)) for x,_ in train])
        testing.append([(x, slope*x+intercept+rng.gauss(0,.04)) for x,_ in test])
    w = 0.0
    b = 0.0
    curve = [round(_score(testing, w, b), 6)]
    for _ in range(rounds):
        # IMPORTANT: The coordinator can access all individual toy gradients
        # in this in-memory demo. This is NOT real secure aggregation.
        gradients = [_gradient(samples, w, b) for samples in training]
        dw = sum(g[0] for g in gradients) / vehicles
        db = sum(g[1] for g in gradients) / vehicles
        w -= .4 * dw
        b -= .4 * db
        curve.append(round(_score(testing, w, b), 6))
    return {
        "simulated": True,
        "publishable": False,
        "real_vehicle_data": False,
        "network_enabled": False,
        "secure_aggregation": False,
        "differential_privacy": False,
        "nodes": vehicles,
        "rounds": rounds,
        "baseline_mae": curve[0],
        "final_mae": curve[-1],
        "improved": curve[-1] < curve[0],
        "learning_curve": curve,
        "warning": "Synthetic model-learning demonstration only. Do not use with real participant data.",
    }
