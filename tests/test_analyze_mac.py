"""Tests for the Mac analysis helpers in scripts/analyze_mac.py."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analyze_mac", ROOT / "scripts/analyze_mac.py")
assert spec and spec.loader
am = importlib.util.module_from_spec(spec)
spec.loader.exec_module(am)


def test_split_counts_per_domain() -> None:
    ids = [f"{d}-{i:03d}" for d in ("healthcare", "general") for i in range(150)]
    split = am.split_of(ids)
    for d in ("healthcare", "general"):
        got = [split[i] for i in ids if i.startswith(d)]
        assert (got.count("train"), got.count("val"), got.count("test")) == (75, 30, 45)


def test_split_is_deterministic_and_disjoint() -> None:
    ids = [f"x-{i}" for i in range(40)]
    assert am.split_of(ids) == am.split_of(list(reversed(ids)))


def test_boot_ci_brackets_mean_and_is_seeded() -> None:
    vals = [0.0, 1.0] * 50
    lo, hi = am.boot_ci(vals)
    assert lo <= 0.5 <= hi
    assert am.boot_ci(vals) == (lo, hi)


def test_mean_power_uses_only_samples_inside_window() -> None:
    samples = [
        {"start": 0.0, "end": 1.0, "dur": 1.0, "w": 10.0},
        {"start": 1.0, "end": 2.0, "dur": 1.0, "w": 20.0},
        {"start": 2.0, "end": 3.5, "dur": 1.5, "w": 99.0},
    ]
    w, n = am.mean_power(samples, 0.0, 3.0)
    assert n == 2
    assert w == pytest.approx(15.0)
    assert am.mean_power(samples, 5.0, 6.0) == (None, 0)


def test_committed_summary_records_optimiser_choice_per_domain() -> None:
    out = json.loads((ROOT / "results/derived/mac_summary.json").read_text())
    choice = out["routing"]["tuned"]["optimiser_choice"]
    assert isinstance(choice, dict) and set(choice) == {
        "healthcare",
        "digital_industries",
        "general_control",
    }
    h3 = out["routing"]["H3"]
    assert h3["selected_on"] == "validation split"
    assert "oracle" not in h3["policy"]
