"""Proposed evidence-bearing instrument, not a standard or legal finding."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    score: float | None
    source: str
    status: str


def score(dimensions: dict[str, Dimension], weights: dict[str, float]) -> float:
    if not weights or set(dimensions) != set(weights):
        raise ValueError("Exact dimension coverage is required")
    if not all(math.isfinite(w) and w >= 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Weights must be nonnegative, finite and have positive total")
    total = 0.0
    for name, dimension in dimensions.items():
        if dimension.score is None or dimension.status != "verified" or not dimension.source:
            raise ValueError("Unknown evidence cannot be silently assigned a sovereignty score")
        if not math.isfinite(dimension.score) or not 0 <= dimension.score <= 1:
            raise ValueError("Dimension score outside [0,1]")
        total += dimension.score * weights[name]
    return total / sum(weights.values())
