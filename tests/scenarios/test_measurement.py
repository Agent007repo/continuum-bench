from dataclasses import replace

import pytest

from continuum_bench.energy import Energy, PowerSample, carbon_grams, cpu_estimate, integrate
from continuum_bench.routing import Candidate, Constraints, choose
from continuum_bench.sovereignty import Dimension, score
from continuum_bench.statistics import cluster_median_interval, quantile


def test_clipped_energy_and_idle():
    energy = integrate([PowerSample(0, 10), PowerSample(2, 20)], 0.5, 1.5, 5, 2)
    assert energy.joules == pytest.approx(10)
    assert energy.provenance == "measured:component-power"


@pytest.mark.parametrize(
    "samples,start,end,idle,gap",
    [
        ([PowerSample(0, 10)], 0, 1, 0, 1),
        ([PowerSample(1, 10), PowerSample(2, 10)], 0, 2, 0, 1),
        ([PowerSample(0, 10), PowerSample(2, 10)], 0, 2, 0, 1),
        ([PowerSample(0, 10), PowerSample(0, 10)], 0, 1, 0, 1),
        ([PowerSample(0, 10), PowerSample(1, 10)], 0, 1, 20, 1),
        ([PowerSample(0, -1), PowerSample(1, 10)], 0, 1, 0, 1),
        ([PowerSample(0, float("nan")), PowerSample(1, 10)], 0, 1, 0, 1),
        ([PowerSample(0, 10), PowerSample(1, 10)], 1, 0, 0, 1),
    ],
)
def test_invalid_energy_rejected(samples, start, end, idle, gap):
    with pytest.raises(ValueError):
        integrate(samples, start, end, idle, gap)


def test_gap_outside_window_ignored():
    e = integrate([PowerSample(-10, 10), PowerSample(0, 10), PowerSample(1, 10)], 0, 1, 0, 1)
    assert e.joules == 10


def test_estimator_provenance_and_carbon():
    e = cpu_estimate(10, 0.5, 5, 25)
    assert e.joules == 100 and e.provenance.startswith("estimated:")
    assert carbon_grams(Energy(3_600_000, "synthetic:fixture", "fixture"), 400) == 400
    with pytest.raises(ValueError):
        cpu_estimate(1, 2, 0, 10)
    with pytest.raises(ValueError):
        cpu_estimate(float("nan"), 0.5, 0, 10)
    with pytest.raises(ValueError):
        carbon_grams(e, -1)


def candidates():
    return [
        Candidate("small", "device", 10, 0.8, 1, 0.8, False, "synthetic"),
        Candidate("large", "device", 30, 0.95, 2, 0.8, False, "synthetic"),
        Candidate("cloud", "cloud", 5, 0.99, 0.5, 0.9, False, "synthetic"),
    ]


def test_special_category_fails_closed():
    c = Constraints(0.7, 5, 0.5, "special-category")
    assert choose(candidates(), c, "constraint").id == "small"
    with pytest.raises(ValueError):
        choose(candidates(), c, "cloud")


def test_all_five_initial_policy_paths():
    c = Constraints(0.7, 5, 0.5, "public")
    assert choose(candidates(), c, "device-small").id == "small"
    assert choose(candidates(), c, "device-large").id == "large"
    assert choose(candidates(), c, "cloud").id == "cloud"
    assert choose(candidates(), c, "static").id == "cloud"
    assert choose(candidates(), replace(c, sensitivity="internal"), "static").id == "small"


def test_no_feasible_route():
    with pytest.raises(ValueError):
        choose(candidates(), Constraints(1, 0.01, 1, "public"), "constraint")
    with pytest.raises(ValueError):
        choose(candidates(), Constraints(0.7, 5, 0.5, "public"), "invented")


def test_mixed_energy_blocked():
    items = candidates()
    items[0] = replace(items[0], energy_provenance="measured")
    with pytest.raises(ValueError):
        choose(items, Constraints(0.7, 5, 0.5, "public"), "constraint")


def test_unknown_score_is_not_zero():
    with pytest.raises(ValueError):
        score({"residency": Dimension(None, "", "pending")}, {"residency": 1})
    assert (
        score(
            {"residency": Dimension(0.8, "synthetic fixture source", "verified")}, {"residency": 2}
        )
        == 0.8
    )


@pytest.mark.parametrize("weights", [{}, {"x": -1}, {"x": 0}, {"x": float("nan")}])
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        score({"x": Dimension(0.8, "fixture", "verified")}, weights)


def test_invalid_dimension_score():
    with pytest.raises(ValueError):
        score({"x": Dimension(2, "fixture", "verified")}, {"x": 1})


def test_bootstrap_clusters_reproducible():
    result = cluster_median_interval({"a": [1, 1], "b": [3, 3]}, resamples=100)
    assert result[0] == 2 and result == cluster_median_interval(
        {"a": [1, 1], "b": [3, 3]}, resamples=100
    )
    assert result[1] <= result[0] <= result[2]
    assert quantile([1, 2, 3], 0.95) == pytest.approx(2.9)
    assert quantile([1, 2, 3], 0.5) == 2


@pytest.mark.parametrize(
    "clusters", [{"a": [1]}, {"a": [], "b": [2]}, {"a": [float("nan")], "b": [2]}]
)
def test_invalid_bootstrap(clusters):
    with pytest.raises(ValueError):
        cluster_median_interval(clusters)


@pytest.mark.parametrize("values,q", [([], 0.5), ([1], -1), ([float("nan")], 0.5)])
def test_invalid_quantile(values, q):
    with pytest.raises(ValueError):
        quantile(values, q)


def test_candidate_and_constraint_validation():
    with pytest.raises(ValueError):
        replace(candidates()[0], energy_j=-1)
    with pytest.raises(ValueError):
        replace(candidates()[0], predicted_quality=2)
    with pytest.raises(ValueError):
        replace(candidates()[0], energy_j=float("nan"))
    with pytest.raises(ValueError):
        Constraints(2, 1, 0.5, "public")
    with pytest.raises(ValueError):
        Constraints(0.5, -1, 0.5, "public")
    with pytest.raises(ValueError):
        Constraints(0.5, float("nan"), 0.5, "public")
    with pytest.raises(ValueError):
        Constraints(0.5, 1, 0.5, "invalid")
