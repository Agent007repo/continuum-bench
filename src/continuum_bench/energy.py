"""Integrate timestamped component power; never imply wall-power measurement."""

import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PowerSample:
    time_s: float
    watts: float


@dataclass(frozen=True)
class Energy:
    joules: float
    provenance: Literal["measured:component-power", "estimated:cpu-linear", "synthetic:fixture"]
    method: str


def integrate(
    samples: list[PowerSample], start_s: float, end_s: float, idle_watts: float, max_gap_s: float
) -> Energy:
    """Piecewise-linear trapezoids clipped to request bounds, without extrapolation."""
    values = [
        start_s,
        end_s,
        idle_watts,
        max_gap_s,
        *[v for s in samples for v in (s.time_s, s.watts)],
    ]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Nonfinite sample or bound")
    if end_s <= start_s or idle_watts < 0 or max_gap_s <= 0:
        raise ValueError("Invalid integration window or baseline")
    if len(samples) < 2:
        raise ValueError("Two bracketing samples required")
    if any(s.watts < 0 for s in samples):
        raise ValueError("Negative physical power")
    if any(b.time_s <= a.time_s for a, b in zip(samples, samples[1:], strict=False)):
        raise ValueError("Samples must be strictly ordered")
    if samples[0].time_s > start_s or samples[-1].time_s < end_s:
        raise ValueError("Request is not bracketed by samples")
    joules = 0.0
    for a, b in zip(samples, samples[1:], strict=False):
        lo, hi = max(start_s, a.time_s), min(end_s, b.time_s)
        if hi <= lo:
            continue
        if b.time_s - a.time_s > max_gap_s:
            raise ValueError("Missing power coverage: excessive sampling gap")
        slope = (b.watts - a.watts) / (b.time_s - a.time_s)
        wlo = a.watts + slope * (lo - a.time_s)
        whi = a.watts + slope * (hi - a.time_s)
        joules += (hi - lo) * ((wlo + whi) / 2 - idle_watts)
    # Negative dynamic energy is evidence of noisy baseline, not zero consumption.
    if joules < 0:
        raise ValueError("Negative baseline-subtracted energy; retain and inspect raw run")
    return Energy(
        joules, "measured:component-power", "trapezoid; idle-subtracted; selected channels"
    )


def cpu_estimate(
    duration_s: float, utilisation: float, idle_watts: float, max_watts: float
) -> Energy:
    if not all(math.isfinite(v) for v in (duration_s, utilisation, idle_watts, max_watts)):
        raise ValueError("Nonfinite estimate")
    if duration_s < 0 or not 0 <= utilisation <= 1 or not 0 <= idle_watts <= max_watts:
        raise ValueError("Invalid estimated-power parameters")
    return Energy(
        duration_s * utilisation * (max_watts - idle_watts),
        "estimated:cpu-linear",
        "Assumed linear utilisation model; not device measurement",
    )


def carbon_grams(energy: Energy, grams_per_kwh: float) -> float:
    if not math.isfinite(grams_per_kwh) or grams_per_kwh < 0:
        raise ValueError("Invalid carbon intensity")
    return energy.joules / 3_600_000 * grams_per_kwh
