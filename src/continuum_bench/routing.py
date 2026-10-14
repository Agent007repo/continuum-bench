"""Placement uses prior validation estimates, never held-out answer scores."""

import math
from dataclasses import dataclass
from typing import Literal

Sensitivity = Literal["public", "internal", "confidential", "special-category"]


@dataclass(frozen=True)
class Candidate:
    id: str
    tier: Literal["device", "edge-emulated", "cloud"]
    energy_j: float
    predicted_quality: float
    predicted_latency_s: float
    sovereignty_score: float
    residency_verified: bool
    energy_provenance: str

    def __post_init__(self) -> None:
        metrics = (
            self.energy_j,
            self.predicted_quality,
            self.predicted_latency_s,
            self.sovereignty_score,
        )
        if not all(math.isfinite(v) for v in metrics):
            raise ValueError("Nonfinite placement metric")
        if self.energy_j < 0 or self.predicted_latency_s < 0:
            raise ValueError("Negative placement metric")
        if not 0 <= self.predicted_quality <= 1 or not 0 <= self.sovereignty_score <= 1:
            raise ValueError("Quality and sovereignty must be in [0,1]")


@dataclass(frozen=True)
class Constraints:
    quality_floor: float
    latency_slo_s: float
    sovereignty_floor: float
    sensitivity: Sensitivity

    def __post_init__(self) -> None:
        if self.sensitivity not in {"public", "internal", "confidential", "special-category"}:
            raise ValueError("Unknown sensitivity class")
        if not all(
            math.isfinite(v)
            for v in (self.quality_floor, self.latency_slo_s, self.sovereignty_floor)
        ):
            raise ValueError("Nonfinite constraint")
        if not 0 <= self.quality_floor <= 1 or not 0 <= self.sovereignty_floor <= 1:
            raise ValueError("Constraint score outside [0,1]")
        if self.latency_slo_s < 0:
            raise ValueError("Negative latency SLO")


def eligible(candidate: Candidate, constraints: Constraints) -> bool:
    return (
        candidate.predicted_quality >= constraints.quality_floor
        and candidate.predicted_latency_s <= constraints.latency_slo_s
        and candidate.sovereignty_score >= constraints.sovereignty_floor
        and (
            constraints.sensitivity not in {"confidential", "special-category"}
            or candidate.tier == "device"
            or candidate.residency_verified
        )
    )


def choose(
    candidates: list[Candidate],
    constraints: Constraints,
    policy: Literal["device-small", "device-large", "cloud", "static", "constraint"],
) -> Candidate:
    if policy not in {"device-small", "device-large", "cloud", "static", "constraint"}:
        raise ValueError("Unsupported policy")
    valid = [c for c in candidates if eligible(c, constraints)]
    if policy.startswith("device"):
        valid = [c for c in valid if c.tier == "device"]
    if policy == "cloud":
        valid = [c for c in valid if c.tier == "cloud"]
    if policy == "static" and constraints.sensitivity != "public":
        valid = [c for c in valid if c.tier == "device"]
    if not valid:
        raise ValueError("No feasible placement; abstain rather than relaxing constraints")
    if policy == "device-large":
        return min(valid, key=lambda c: (-c.predicted_quality, c.id))
    provenance = {c.energy_provenance for c in valid}
    if len(provenance) != 1:
        raise ValueError("Mixed energy provenance: compare sensitivity strata separately")
    return min(valid, key=lambda c: (c.energy_j, c.predicted_latency_s, c.id))
