"""Small dependency-free bootstrap, using item clusters as resampling units."""

import math
import random
from statistics import median


def quantile(values: list[float], q: float) -> float:
    if not values or not 0 <= q <= 1 or not all(math.isfinite(x) for x in values):
        raise ValueError("Invalid quantile inputs")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    return (
        ordered[low] * (high - pos) + ordered[high] * (pos - low) if low != high else ordered[low]
    )


def cluster_median_interval(
    clusters: dict[str, list[float]], resamples: int = 2000, seed: int = 20261013
) -> tuple[float, float, float]:
    if len(clusters) < 2 or resamples < 100:
        raise ValueError("At least two item clusters and 100 bootstrap resamples required")
    for values in clusters.values():
        if not values or not all(math.isfinite(v) for v in values):
            raise ValueError("Empty or nonfinite cluster")
    items = sorted(clusters)
    rng = random.Random(seed)
    estimates = []
    for _ in range(resamples):
        selected = rng.choices(items, k=len(items))
        estimates.append(median(v for item in selected for v in clusters[item]))
    observed = median(v for item in items for v in clusters[item])
    return observed, quantile(estimates, 0.025), quantile(estimates, 0.975)
