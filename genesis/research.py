"""Bounded, reproducible autonomous research candidates.

Discover relationships between allowlisted signals by testing multiple feature /
target pairs on forward-only held-out samples. Associations are NOT causal
discoveries, do not predict the future, and cannot be promoted automatically.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .source import ALLOWED_METRICS

TARGETS = ("battery_temp_c", "pack_power_kw", "charger_power_kw",
           "module_temp_spread_c", "pack_current_abs_a", "battery_level")
FEATURES = ("outside_temp_c", "speed_kmh", "battery_temp_c",
            "charger_power_kw", "pack_current_abs_a", "power_kw",
            "preconditioning", "battery_heater_on")
MIN_PAIR_ROWS = 140
MIN_SPACING_S = 600
MAX_CANDIDATES = 40
MIN_IMPROVEMENT = 0.10

@dataclass(frozen=True)
class Hypothesis:
    target: str
    feature: str
    evidence_rows: int
    train_rows: int
    test_rows: int
    baseline_mae: float
    candidate_mae: float
    improvement_pct: float
    slope: float
    intercept: float
    status: str
    reason: str

    def public_summary(self) -> dict:
        """Return metadata only, not vehicle observations, timestamps or IDs."""
        return {
            "target": self.target, "feature": self.feature, "status": self.status,
            "train_rows": self.train_rows, "test_rows": self.test_rows,
            "baseline_mae": round(self.baseline_mae, 4),
            "candidate_mae": round(self.candidate_mae, 4),
            "improvement_pct": round(self.improvement_pct, 2),
            "reason": self.reason,
        }

def _mae(pairs: list[tuple[float, float]], predictor) -> float:
    return sum(abs(y - predictor(x)) for x, y in pairs) / len(pairs)

def _linfit(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    mx = statistics.fmean(x for x, _ in pairs)
    my = statistics.fmean(y for _, y in pairs)
    variance = sum((x - mx) ** 2 for x, _ in pairs)
    if variance < 1e-9:
        return 0.0, my
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    slope = cov / variance
    return slope, my - slope * mx

def _thin(rows: list[dict]) -> list[dict]:
    # Autocorrelated minute-by-minute samples inflate apparent evidence.
    out = []
    previous = -float("inf")
    for row in sorted(rows, key=lambda x: x["ts"]):
        ts = row["ts"]
        if ts >= previous + MIN_SPACING_S:
            out.append(row)
            previous = ts
    return out

def discover(rows: list[dict], max_candidates: int = MAX_CANDIDATES) -> list[Hypothesis]:
    spaced = _thin(rows)
    if not spaced:
        return []
    available = set(spaced[0])
    candidates = [(y, x) for y in TARGETS for x in FEATURES
                  if y != x and y in available and x in available
                  and y in ALLOWED_METRICS and x in ALLOWED_METRICS]
    findings = []
    for target, feature in candidates[:max(1, min(int(max_candidates), MAX_CANDIDATES))]:
        pairs = [(r[feature], r[target]) for r in spaced
                 if r.get(feature) is not None and r.get(target) is not None]
        if len(pairs) < MIN_PAIR_ROWS:
            continue
        train_end = int(len(pairs) * .70)
        # Embargo ten samples around temporal boundary to reduce train/test leakage.
        train, test = pairs[:train_end], pairs[train_end + 10:]
        if len(train) < 90 or len(test) < 30:
            continue
        slope, intercept = _linfit(train)
        if not all(math.isfinite(v) for v in (slope, intercept)):
            continue
        center = statistics.fmean(y for _, y in train)
        baseline = _mae(test, lambda x: center)
        candidate = _mae(test, lambda x: slope * x + intercept)
        if baseline < 1e-6 or not math.isfinite(candidate):
            continue
        improvement = (baseline - candidate) / baseline
        mid = len(test) // 2
        segments = (test[:mid], test[mid:])
        stable = all(
            _mae(segment, lambda x: slope * x + intercept) <
            _mae(segment, lambda x: center)
            for segment in segments
        )
        accepted = improvement >= MIN_IMPROVEMENT and stable
        findings.append(Hypothesis(
            target=target, feature=feature, evidence_rows=len(pairs),
            train_rows=len(train), test_rows=len(test),
            baseline_mae=baseline, candidate_mae=candidate,
            improvement_pct=100 * improvement, slope=slope, intercept=intercept,
            status="SHADOW" if accepted else "REJECTED",
            reason=("Out-of-time segments both improved; experimental association only."
                    if accepted else "Insufficient holdout improvement or stability."),
        ))
    return sorted(findings, key=lambda h: h.improvement_pct, reverse=True)
