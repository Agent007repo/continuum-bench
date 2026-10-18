"""Analyse the Mac benchmark: quality, latency, measured energy, sovereignty and routing.

Inputs (committed under results/mac/):
  pilot/*.jsonl, pilot/*.manifest.json             pilot cells (sizing only)
  confirmatory/*.jsonl, *.timing.jsonl, *.manifest.json
  powermetrics.txt                                 sudo powermetrics text output
  markers.txt                                      phase markers (epoch seconds)
Outputs:
  results/derived/mac_*.json, results/figures/*.png, paper/generated/*.tex

Every energy number carries provenance "measured" (device tier) or
"measured-emulated-tier" (edge tier). Routing is fitted on train, tuned on validation
and reported on test; the oracle is labelled as an unattainable upper bound.
"""

import datetime as dt
import json
import random
import re
import statistics as st
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parents[1]
R = root / "results/mac"
D = root / "results/derived"
FIG = root / "results/figures"
GEN = root / "paper/generated"
for p in (D, FIG, GEN):
    p.mkdir(parents=True, exist_ok=True)
proto = json.loads((root / "configs/2026-10-17-mac-v1.json").read_text())
v11 = root / "configs/2026-10-17-mac-v1.1.json"
thresholds = json.loads(v11.read_text())["hypotheses"] if v11.exists() else {"X": None, "Y": None}
SEED = 20261017
BIG = ("qwen7b-q4", "device")


# ---------------------------------------------------------------- loading
def load_phase(phase: str) -> tuple[list[dict], dict[str, dict]]:
    rows, mans = [], {}
    for f in sorted((R / phase).glob("*.jsonl")):
        if f.name.endswith(".timing.jsonl"):
            continue
        rows += [json.loads(x) for x in f.read_text().splitlines() if x]
    for f in sorted((R / phase).glob("*.manifest.json")):
        m = json.loads(f.read_text())
        mans[m["stem"]] = m
    return rows, mans


def markers() -> dict[str, float]:
    out = {}
    p = R / "markers.txt"
    if p.exists():
        for line in p.read_text().splitlines():
            *name, t = line.split()
            out[" ".join(name)] = float(t)
    return out


# ---------------------------------------------------------------- power
HDR = re.compile(r"\*\*\* Sampled system activity \((.+?)\) \(([\d.]+)ms elapsed\) \*\*\*")
PWR = re.compile(r"^(CPU|GPU|ANE) Power:\s*([\d.]+)\s*mW", re.M)
COMB = re.compile(r"Combined Power \(CPU \+ GPU \+ ANE\):\s*([\d.]+)\s*mW")


def power_samples(shift_s: float = 0.0) -> list[dict]:
    """Parse powermetrics text into samples with reconstructed end times.

    Headers carry wall time at one-second resolution. We anchor the cumulative
    'elapsed' sum to the headers (median offset plus 0.5 s) to get sub-second end times."""
    p = R / "powermetrics.txt"
    if not p.exists():
        return []
    text = p.read_text(errors="ignore")
    parts = HDR.split(text)
    samples, cum = [], 0.0
    for i in range(1, len(parts) - 2, 3):
        stamp, elapsed, body = parts[i], float(parts[i + 1]), parts[i + 2]
        try:
            t = dt.datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y %z").timestamp()
        except ValueError:
            continue
        cum += elapsed / 1000
        rails = {k: float(v) / 1000 for k, v in PWR.findall(body)}
        comb = COMB.search(body)
        total = float(comb.group(1)) / 1000 if comb else sum(rails.values())
        samples.append({"hdr": t, "cum": cum, "dur": elapsed / 1000, "w": total, **rails})
    if not samples:
        return []
    offset = st.median(s["hdr"] - s["cum"] for s in samples) + 0.5 + shift_s
    for s in samples:
        s["end"] = offset + s["cum"]
        s["start"] = s["end"] - s["dur"]
    return samples


def mean_power(samples: list[dict], t0: float, t1: float) -> tuple[float | None, int]:
    inside = [s for s in samples if s["start"] >= t0 and s["end"] <= t1]
    if not inside:
        return None, 0
    w = sum(s["w"] * s["dur"] for s in inside) / sum(s["dur"] for s in inside)
    return w, len(inside)


# ---------------------------------------------------------------- stats
def boot_ci(vals: list[float], n: int = 2000, seed: int = SEED) -> tuple[float, float]:
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    k = len(vals)
    means = sorted(sum(vals[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def pct(vals: list[float], q: float) -> float:
    return float(np.percentile(vals, q)) if vals else float("nan")


def split_of(item_ids: list[str]) -> dict[str, str]:
    """Train 50, validation 20, test 30 per domain prefix, seeded."""
    out = {}
    by_dom: dict[str, list[str]] = {}
    for i in sorted(item_ids):
        by_dom.setdefault(i.split("-")[0], []).append(i)
    rng = random.Random(SEED)
    for _dom, ids in sorted(by_dom.items()):
        ids = ids[:]
        rng.shuffle(ids)
        n = len(ids)
        a, b = round(0.5 * n), round(0.7 * n)
        for j, x in enumerate(ids):
            out[x] = "train" if j < a else ("val" if j < b else "test")
    return out


# ---------------------------------------------------------------- main analysis
def main() -> None:
    rows, mans = load_phase("confirmatory")
    prow, pmans = load_phase("pilot")
    mk = markers()
    samples = power_samples()
    status = {
        "confirmatory_rows": len(rows),
        "pilot_rows": len(prow),
        "power_samples": len(samples),
    }
    if not rows:
        (D / "mac_summary.json").write_text(
            json.dumps({"status": "pending", **status}, indent=1) + "\n"
        )
        print("pending", status)
        return

    idle = None
    if "idle_start" in mk and "idle_end" in mk and samples:
        idle_w, idle_n = mean_power(samples, mk["idle_start"] + 2, mk["idle_end"] - 2)
        a, _ = mean_power(samples, mk["idle_start"] + 2, mk["idle_start"] + 30)
        b, _ = mean_power(samples, mk["idle_end"] - 30, mk["idle_end"] - 2)
        idle = {"w": idle_w, "n": idle_n, "first30_w": a, "last30_w": b}

    # energy per cell (config x tier x domain)
    cells = {}
    for stem, m in mans.items():
        t0, t1 = m["windows_epoch"]["main"]
        p, n = mean_power(samples, t0, t1)
        e = None
        if p is not None and idle and idle["w"] is not None:
            win = t1 - t0
            e = {
                "joules_per_request": (p - idle["w"]) * win / m["n_items"],
                "joules_per_request_idle_first30": (p - idle["first30_w"]) * win / m["n_items"]
                if idle["first30_w"]
                else None,
                "joules_per_request_idle_last30": (p - idle["last30_w"]) * win / m["n_items"]
                if idle["last30_w"]
                else None,
                "mean_power_w": p,
                "samples": n,
                "window_s": win,
                "provenance": "measured"
                if m["tier"]["name"] == "device"
                else "measured-emulated-tier",
            }
        cells[stem] = {
            "config": m["config"]["id"],
            "tier": m["tier"]["name"],
            "domain": m["domain"],
            "swapped": m["swapped"],
            "thermal_before": m["thermal_before"],
            "peak_rss_gb": m["peak_rss_raw"] / (1 << 30)
            if m["peak_rss_unit"] == "bytes"
            else m["peak_rss_raw"] / (1 << 20),
            "energy": e,
        }

    # per config x tier summaries
    keys = sorted({(r["config"], r["tier"]) for r in rows})
    by_key: dict[tuple[str, str], list[dict]] = {
        k: [r for r in rows if (r["config"], r["tier"]) == k] for k in keys
    }
    summary = {}
    for k, rs in by_key.items():
        acc = [1.0 if r["correct"] else 0.0 for r in rs]
        cs = [c for c in cells.values() if (c["config"], c["tier"]) == k]
        swapped_domains = {c["domain"] for c in cs if c["swapped"]}
        # protocol: cells with page-outs are excluded from latency and energy
        lat = [r["wall_s"] for r in rs if r["domain"] not in swapped_domains]
        ej = [c["energy"]["joules_per_request"] for c in cs if c["energy"] and not c["swapped"]]
        summary[f"{k[0]}|{k[1]}"] = {
            "n": len(rs),
            "accuracy": sum(acc) / len(acc),
            "accuracy_ci": boot_ci(acc),
            "accuracy_by_domain": {
                d: st.mean(1.0 if r["correct"] else 0.0 for r in rs if r["domain"] == d)
                for d in sorted({r["domain"] for r in rs})
            },
            "latency_median_s": st.median(lat),
            "latency_p95_s": pct(lat, 95),
            "latency_domains_excluded": sorted(swapped_domains),
            "no_label_rate": sum(r["pred"] is None for r in rs) / len(rs),
            "joules_per_request_mean_over_domains": st.mean(ej)
            if len(ej) == len(cs) and ej
            else None,
            "energy_provenance": "measured" if k[1] == "device" else "measured-emulated-tier",
            "peak_rss_gb": max(c["peak_rss_gb"] for c in cs),
            "any_swap": any(c["swapped"] for c in cs),
        }

    # timing replay stability
    replay = {}
    for f in sorted((R / "confirmatory").glob("*.timing.jsonl")):
        ts = [json.loads(x) for x in f.read_text().splitlines() if x]
        per_item: dict[str, list[float]] = {}
        for t in ts:
            per_item.setdefault(t["item_id"], []).append(t["wall_s"])
        cvs = [
            st.pstdev(v) / st.mean(v) for v in per_item.values() if len(v) > 1 and st.mean(v) > 0
        ]
        replay[f.name.replace(".timing.jsonl", "")] = {
            "median_cv": st.median(cvs) if cvs else None,
            "reps": max(len(v) for v in per_item.values()),
        }

    # paired accuracy difference, Mistral-7B minus Qwen2.5-1.5B, on the same items
    acc_by = {
        (r["config"], r["item_id"]): 1.0 if r["correct"] else 0.0
        for r in rows
        if r["tier"] == "device"
    }
    shared = sorted(i for (c, i) in acc_by if c == "mistral7b-q4" and ("qwen1.5b-q4", i) in acc_by)
    md = [acc_by[("mistral7b-q4", i)] - acc_by[("qwen1.5b-q4", i)] for i in shared]
    paired = {
        "mistral7b_minus_qwen1.5b_pts": 100 * st.mean(md) if md else None,
        "ci_pts": [100 * x for x in boot_ci(md)] if md else None,
        "n": len(md),
    }
    # sensitivity: shift the power-sample clock by +/- 0.5 s (header resolution is 1 s)
    clock = {}
    for shift in (-0.5, 0.5):
        ss = power_samples(shift)
        for stem, m in mans.items():
            c = cells[stem]
            if not c["energy"] or c["swapped"]:
                continue
            t0, t1 = m["windows_epoch"]["main"]
            p2, _ = mean_power(ss, t0, t1)
            if p2 is None:
                continue
            j2 = (p2 - idle["w"]) * (t1 - t0) / m["n_items"]
            ch = 100 * (j2 / c["energy"]["joules_per_request"] - 1)
            clock.setdefault(stem, []).append(ch)
    idle_sens = [
        100 * abs(c["energy"][k] / c["energy"]["joules_per_request"] - 1)
        for c in cells.values()
        if c["energy"] and not c["swapped"]
        for k in ("joules_per_request_idle_first30", "joules_per_request_idle_last30")
        if c["energy"][k]
    ]
    sensitivity = {
        "clock_shift_half_second_max_abs_pct": max(abs(x) for v in clock.values() for x in v)
        if clock
        else None,
        "clock_shift_max_abs_pct_by_size": {
            size: max(
                (abs(x) for k, v in clock.items() if k.startswith(size) for x in v), default=None
            )
            for size in ("qwen0.5b", "qwen1.5b", "qwen7b", "mistral7b")
        },
        "idle_window_max_abs_pct": max(idle_sens) if idle_sens else None,
    }

    routing = route(rows, cells, summary)
    sov = sovereignty()
    out = {
        "status": "complete",
        **status,
        "idle": idle,
        "cells": cells,
        "summary": summary,
        "replay": replay,
        "routing": routing,
        "paired_accuracy": paired,
        "energy_sensitivity": sensitivity,
        "sovereignty": sov,
        "thresholds": thresholds,
    }
    (D / "mac_summary.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    figures(summary, routing)
    tex(out)
    prose(out)
    readme_block(out)
    appendix(out)
    explorer(out)
    print(
        json.dumps(
            {
                k: (round(v["accuracy"], 3), v["joules_per_request_mean_over_domains"])
                for k, v in summary.items()
            },
            indent=1,
        )
    )


# ---------------------------------------------------------------- routing
def route(rows: list[dict], cells: dict, summary: dict) -> dict:
    dev = [r for r in rows if r["tier"] == "device"]
    configs = sorted({r["config"] for r in dev})
    table = {(r["config"], r["item_id"]): r for r in dev}
    items = sorted({r["item_id"] for r in dev})
    split = split_of(items)
    dom_of = {r["item_id"]: r["domain"] for r in dev}
    sens = {
        r["item_id"]: (
            "special-category"
            if r["domain"] == "healthcare"
            else "confidential"
            if r["domain"] == "digital_industries"
            else "public"
        )
        for r in dev
    }

    def energy(cfg: str, item: str) -> float | None:
        c = cells.get(f"{cfg}__device__{dom_of[item]}__confirmatory")
        return c["energy"]["joules_per_request"] if c and c["energy"] else None

    def lat(cfg: str, item: str) -> float:
        return table[(cfg, item)]["wall_s"]

    have_energy = all(energy(c, i) is not None for c in configs for i in items[:1])

    def evaluate(choice: dict[str, list[str]], subset: str) -> dict:
        ids = [i for i in items if split[i] == subset]
        acc, ej, lt = [], [], []
        for i in ids:
            path = choice[i]
            final = path[-1]
            acc.append(1.0 if table[(final, i)]["correct"] else 0.0)
            lt.append(sum(lat(c, i) for c in path))
            if have_energy:
                ej.append(sum(energy(c, i) for c in path))
        res = {
            "n": len(ids),
            "escalation_rate": st.mean(1.0 if len(choice[i]) > 1 else 0.0 for i in ids),
            "accuracy": st.mean(acc),
            "accuracy_ci": boot_ci(acc),
            "latency_mean_s": st.mean(lt),
        }
        if have_energy:
            res |= {"joules_mean": st.mean(ej), "joules_ci": boot_ci(ej)}
        res["paired"] = {"acc": acc, "j": ej}
        return res

    policies: dict[str, dict] = {}
    for c in configs:
        policies[f"always {c}"] = {i: [c] for i in items}

    small, big = "qwen1.5b-q4", BIG[0]
    eu = [c for c in configs if c.startswith("mistral")]
    # static sensitivity rule: special-category and confidential items stay on the EU-origin model
    if eu:
        policies["static sensitivity rule"] = {
            i: ([eu[0]] if sens[i] != "public" else [small]) for i in items
        }

    def tune_cascade(signal: str) -> tuple[float, dict]:
        best = None
        for tau in np.linspace(0.3, 0.99, 70):
            ch = {i: ([small] if table[(small, i)][signal] >= tau else [small, big]) for i in items}
            v = evaluate(ch, "val")
            bigv = evaluate({i: [big] for i in items}, "val")
            ok = v["accuracy"] >= bigv["accuracy"] - (thresholds.get("Y") or 0) / 100
            cost = v.get("joules_mean", v["latency_mean_s"])
            if ok and (best is None or cost < best[0]):
                best = (cost, float(tau), ch)
        if best is None:
            return 1.0, {i: [small, big] for i in items}
        return best[1], best[2]

    tau_p, policies["cascade p_max"] = tune_cascade("p_max")
    tau_m, policies["cascade margin"] = tune_cascade("margin")

    # learned router: logistic regression on small-model signals, fit on train
    doms = sorted(set(dom_of.values()))

    def feats(i: str) -> list[float]:
        r = table[(small, i)]
        return [1.0, r["p_max"], r["margin"], r["prompt_tokens"] / 500] + [
            1.0 if dom_of[i] == d else 0.0 for d in doms[1:]
        ]

    tr = [i for i in items if split[i] == "train"]
    X = np.array([feats(i) for i in tr])
    y = np.array([1.0 if table[(small, i)]["correct"] else 0.0 for i in tr])
    w = np.zeros(X.shape[1])
    for _ in range(4000):
        p = 1 / (1 + np.exp(-X @ w))
        w -= 0.1 * (X.T @ (p - y) / len(y) + 1e-3 * w)
    best = None
    for th in np.linspace(0.3, 0.95, 66):
        ch = {
            i: ([small] if 1 / (1 + np.exp(-np.array(feats(i)) @ w)) >= th else [small, big])
            for i in items
        }
        v = evaluate(ch, "val")
        bigv = evaluate({i: [big] for i in items}, "val")
        if v["accuracy"] >= bigv["accuracy"] - (thresholds.get("Y") or 0) / 100:
            cost = v.get("joules_mean", v["latency_mean_s"])
            if best is None or cost < best[0]:
                best = (cost, float(th), ch)
    th_lr = best[1] if best else None
    policies["learned router"] = best[2] if best else {i: [small, big] for i in items}

    # constraint-aware optimiser: per domain, cheapest config whose validation accuracy clears the floor
    floor_drop = (thresholds.get("Y") or 0) / 100
    opt_choice: dict[str, str] = {}
    for d in doms:
        vids = [i for i in items if split[i] == "val" and dom_of[i] == d]
        bigacc = st.mean(1.0 if table[(big, i)]["correct"] else 0.0 for i in vids)
        cands = []
        for c in configs:
            a = st.mean(1.0 if table[(c, i)]["correct"] else 0.0 for i in vids)
            cost = st.mean((energy(c, i) if have_energy else lat(c, i)) for i in vids)
            if a >= bigacc - floor_drop:
                cands.append((cost, c))
        opt_choice[d] = min(cands)[1] if cands else big
    policies["constraint-aware optimiser"] = {i: [opt_choice[dom_of[i]]] for i in items}

    # oracle upper bound (uses test labels; unattainable)
    order = sorted(
        configs,
        key=lambda c: (
            summary[f"{c}|device"]["joules_per_request_mean_over_domains"]
            or summary[f"{c}|device"]["latency_median_s"]
        ),
    )
    policies["oracle (upper bound, uses labels)"] = {
        i: [next((c for c in order if table[(c, i)]["correct"]), big)] for i in items
    }

    results = {name: evaluate(ch, "test") for name, ch in policies.items()}
    base = results[f"always {big}"]
    base_paired = base["paired"]
    for r in results.values():
        if have_energy:
            r["energy_saving_vs_big_pct"] = 100 * (1 - r["joules_mean"] / base["joules_mean"])
            diffs = [b - a for a, b in zip(r["paired"]["j"], base_paired["j"], strict=True)]
            r["saving_j_ci"] = boot_ci(diffs)
        dacc = [a - b for a, b in zip(r["paired"]["acc"], base_paired["acc"], strict=True)]
        r["accuracy_diff_vs_big_pts"] = 100 * st.mean(dacc)
        r["accuracy_diff_ci_pts"] = tuple(100 * x for x in boot_ci(dacc))
        r.pop("paired")
    # H3: choose the policy on VALIDATION (no test peeking), then report it on test.
    h3 = None
    if thresholds.get("X") is not None and have_energy:
        valres = {n: evaluate(ch, "val") for n, ch in policies.items()}
        vbase = valres[f"always {big}"]
        cands = {}
        for n, v in valres.items():
            if n.startswith("always") or "oracle" in n:
                continue
            dacc = 100 * (v["accuracy"] - vbase["accuracy"])
            sav = 100 * (1 - v["joules_mean"] / vbase["joules_mean"])
            if dacc >= -thresholds["Y"]:
                cands[n] = (sav, dacc)
        if cands:
            h3_choice = max(cands, key=lambda n: cands[n][0])
            b = results[h3_choice]
            base_j = results[f"always {big}"]["joules_mean"]
            sav_pct_ci = [100 * x / base_j for x in b["saving_j_ci"]]
            h3 = {
                "selected_on": "validation split",
                "candidate_set": "non-oracle routing policies (cascades, learned router, optimiser, static rule); single-configuration baselines are reported separately",
                "policy": h3_choice,
                "validation_saving_pct": cands[h3_choice][0],
                "validation_accuracy_diff_pts": cands[h3_choice][1],
                "test_escalation_rate": b["escalation_rate"],
                "test_saving_pct_ci": sav_pct_ci,
                "energy_ci_meets_X": sav_pct_ci[0] >= thresholds["X"],
                "test_saving_pct": b["energy_saving_vs_big_pct"],
                "test_saving_j_ci": b["saving_j_ci"],
                "test_accuracy_diff_pts": b["accuracy_diff_vs_big_pts"],
                "test_accuracy_diff_ci_pts": b["accuracy_diff_ci_pts"],
                "supported_on_point_estimates": b["energy_saving_vs_big_pct"] >= thresholds["X"]
                and b["accuracy_diff_vs_big_pts"] >= -thresholds["Y"],
                "accuracy_ci_within_tolerance": b["accuracy_diff_ci_pts"][0] >= -thresholds["Y"],
            }
        else:
            h3 = {"selected_on": "validation split", "policy": None}

    def acc_on(cfg_or_policy: dict[str, list[str]], subset: str) -> float:
        ids = [i for i in items if split[i] == subset]
        return st.mean(1.0 if table[(cfg_or_policy[i][-1], i)]["correct"] else 0.0 for i in ids)

    split_deltas = {}
    for name in ("always qwen1.5b-q4", h3["policy"] if h3 and h3.get("policy") else None):
        if name:
            split_deltas[name] = {
                sub: 100 * (acc_on(policies[name], sub) - acc_on(policies[f"always {big}"], sub))
                for sub in ("train", "val", "test")
            }
    # sensitivity: apportion each cell's energy by item wall time instead of evenly
    wall_share = {}
    for c in configs:
        for d in doms:
            ids_d = [i for i in items if dom_of[i] == d]
            tot = sum(lat(c, i) for i in ids_d)
            e = energy(c, ids_d[0])
            for i in ids_d:
                wall_share[(c, i)] = None if e is None else e * len(ids_d) * lat(c, i) / tot
    wall_sens = None
    if h3 and h3.get("policy") and have_energy:
        tids = [i for i in items if split[i] == "test"]

        def jmean(pol: dict[str, list[str]]) -> float:
            return st.mean(sum(wall_share[(c, i)] for c in pol[i]) for i in tids)

        wall_sens = 100 * (1 - jmean(policies[h3["policy"]]) / jmean(policies[f"always {big}"]))
    return {
        "split_deltas_vs_big_pts": split_deltas,
        "h3_saving_pct_wall_time_apportioned": wall_sens,
        "split_counts": {s: sum(v == s for v in split.values()) for s in ("train", "val", "test")},
        "tuned": {
            "cascade_p_max_tau": tau_p,
            "cascade_margin_tau": tau_m,
            "router_threshold": th_lr,
            "optimiser_choice": opt_choice,
        },
        "policies": results,
        "H3": h3,
        "energy_available": have_energy,
    }


# ---------------------------------------------------------------- sovereignty
def sovereignty() -> dict:
    """Score configurations and characterised cloud options on six dimensions (0 to 1),
    from configs/sovereignty_inputs.json, with a random-weight sensitivity analysis."""
    p = root / "configs/sovereignty_inputs.json"
    if not p.exists():
        return {"status": "pending: configs/sovereignty_inputs.json missing"}
    inp = json.loads(p.read_text())
    dims = inp["dimensions"]
    opts = inp["options"]
    eq = {o["id"]: st.mean(o["scores"][d] for d in dims) for o in opts}
    rng = np.random.default_rng(SEED)
    wins: dict[str, int] = {o["id"]: 0 for o in opts}
    ranks: dict[str, list[int]] = {o["id"]: [] for o in opts}
    for _ in range(5000):
        wv = rng.dirichlet(np.ones(len(dims)))
        sc = {o["id"]: float(sum(wv[j] * o["scores"][d] for j, d in enumerate(dims))) for o in opts}
        order = sorted(sc, key=lambda k: -sc[k])
        wins[order[0]] += 1
        for r, k in enumerate(order):
            ranks[k].append(r + 1)
    return {
        "equal_weights": eq,
        "top_rank_share": {k: v / 5000 for k, v in wins.items()},
        "median_rank": {k: st.median(v) for k, v in ranks.items()},
        "rank_range": {k: (min(v), max(v)) for k, v in ranks.items()},
        "dimensions": dims,
    }


# ---------------------------------------------------------------- outputs
def figures(summary: dict, routing: dict) -> None:
    """Left: every configuration on all 450 items. Right: policies on the 135 test items."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    pts = [
        (k, v) for k, v in summary.items() if v["joules_per_request_mean_over_domains"] is not None
    ]
    if not pts:
        return
    short = {
        "qwen0.5b-q4": "Q0.5/4",
        "qwen0.5b-q8": "Q0.5/8",
        "qwen1.5b-q4": "Q1.5/4",
        "qwen1.5b-q8": "Q1.5/8",
        "qwen7b-q4": "Q7/4",
        "mistral7b-q4": "M7/4",
    }
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 3.3), sharey=False)
    for k, v in pts:
        cfg, tier = k.split("|")
        x, y = v["joules_per_request_mean_over_domains"], 100 * v["accuracy"]
        dev = tier == "device"
        a1.scatter(
            x,
            y,
            marker="o" if dev else "s",
            s=30,
            color="#1f6f8b" if dev else "#b5651d",
            zorder=3,
            label="GPU (device)" if dev else "CPU (emulated edge)",
        )
        dy = {"qwen1.5b-q8": -9, "qwen0.5b-q4": -9}.get(cfg, 4) if dev else -10
        a1.annotate(
            short.get(cfg, cfg), (x, y), fontsize=6.5, xytext=(4, dy), textcoords="offset points"
        )
    h, lab = a1.get_legend_handles_labels()
    uniq = dict(zip(lab, h, strict=True))
    a1.legend(uniq.values(), uniq.keys(), fontsize=6.5, loc="lower right", frameon=False)
    a1.set_xscale("log")
    a1.set_xlabel("Measured energy per request (J, log)", fontsize=7.5)
    a1.set_ylabel("Accuracy (%)", fontsize=7.5)
    a1.set_title("Configurations, all 450 items", fontsize=8)
    code = {
        "static sensitivity rule": "S",
        "cascade p_max": "Cp",
        "cascade margin": "Cm",
        "learned router": "R",
        "constraint-aware optimiser": "Opt",
        "oracle (upper bound, uses labels)": "oracle",
    }
    offs = {
        "Cp": (4, 4),
        "Cm": (4, -9),
        "R": (-10, 4),
        "Opt": (4, -9),
        "S": (4, 2),
        "oracle": (4, -9),
    }
    for name, r in routing["policies"].items():
        if "joules_mean" not in r:
            continue
        x, y = r["joules_mean"], 100 * r["accuracy"]
        if name.startswith("always"):
            cfg = name.split(" ", 1)[1]
            a2.scatter(
                x, y, marker="o", s=22, color="#9bbfcc", zorder=2, label="single configuration"
            )
            if cfg in ("qwen7b-q4", "qwen1.5b-q4"):
                a2.annotate(
                    short.get(cfg, cfg),
                    (x, y),
                    fontsize=6,
                    xytext=(4, 4 if cfg == "qwen1.5b-q4" else 6),
                    textcoords="offset points",
                    color="#557",
                )
            continue
        oracle = "oracle" in name
        a2.scatter(
            x,
            y,
            marker="^",
            s=32,
            zorder=3,
            facecolors="none" if oracle else "#444",
            edgecolors="#444",
            label="oracle (unattainable)" if oracle else "routing policy",
        )
        a2.annotate(
            code.get(name, name),
            (x, y),
            fontsize=6.5,
            xytext=offs.get(code.get(name, ""), (4, 2)),
            textcoords="offset points",
            color="#333",
        )
    h, lab = a2.get_legend_handles_labels()
    uniq = dict(zip(lab, h, strict=True))
    a2.legend(uniq.values(), uniq.keys(), fontsize=6.5, loc="lower right", frameon=False)
    a2.set_xscale("log")
    a2.set_xlabel("Estimated energy per request (J, log)", fontsize=7.5)
    a2.set_title("Policies, 135 test items (device tier)", fontsize=8)
    for ax in (a1, a2):
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "pareto_energy_accuracy.png", dpi=200)
    plt.close(fig)


def tex(out: dict) -> None:
    s = out["summary"]
    lines = [
        r"\begin{table*}[t]\centering\small",
        r"\caption{Mac results per configuration and tier (450 confirmatory items). Energy is measured incremental component energy (CPU+GPU+ANE minus idle); edge-tier energy is measured on the Mac but the tier is emulated.}\label{tab:mac}",
        r"\begin{tabular}{@{}llrrrrrr@{}}\toprule",
        r"Config & Tier & Acc. & 95\% CI & Med. lat. (s) & p95 lat. (s) & J/request & Peak RSS (GB)\\\midrule",
    ]
    for k, v in s.items():
        cfg, tier = k.split("|")
        j = v["joules_per_request_mean_over_domains"]
        lines.append(
            f"{cfg} & {tier} & {100 * v['accuracy']:.1f} & [{100 * v['accuracy_ci'][0]:.1f}, {100 * v['accuracy_ci'][1]:.1f}] & {v['latency_median_s']:.3f} & {v['latency_p95_s']:.3f} & {'n/a' if j is None else f'{j:.2f}'} & {v['peak_rss_gb']:.1f}\\\\"
        )
    lines.append(r"\bottomrule\end{tabular}\end{table*}")
    (GEN / "mac_table.tex").write_text("\n".join(lines) + "\n")
    rt = out["routing"]["policies"]
    lines = [
        r"\begin{table}[t]\centering\footnotesize",
        r"\caption{Routing policies on the 135 held-out test items, device tier. $\Delta$: accuracy change in points versus always Qwen2.5-7B. Saving: mean energy per request saved versus the same baseline.}\label{tab:routing}",
        r"\begin{tabular}{@{}lrrr@{}}\toprule",
        r"Policy & Acc. & $\Delta$ & Saving\\\midrule",
    ]
    for name, r in rt.items():
        sav = r.get("energy_saving_vs_big_pct")
        lines.append(
            f"{name.replace('_', chr(92) + '_')} & {100 * r['accuracy']:.1f} & {r['accuracy_diff_vs_big_pts']:+.1f} & {'n/a' if sav is None else f'{sav:.0f}\\%'}\\\\"
        )
    lines.append(r"\bottomrule\end{tabular}\end{table}")
    (GEN / "routing_table.tex").write_text("\n".join(lines) + "\n")


def prose(out: dict) -> None:
    """Data-driven paragraphs for the report. Every number is read from `out`."""
    s, rt, h3 = out["summary"], out["routing"]["policies"], out["routing"]["H3"]
    th = out["thresholds"]
    big = s["qwen7b-q4|device"]
    q15 = s["qwen1.5b-q4|device"]
    q05 = s["qwen0.5b-q4|device"]
    e05 = s["qwen0.5b-q4|edge"]
    excl = sorted(k for k, c in out["cells"].items() if c["swapped"])
    pw = [
        c["energy"]["mean_power_w"]
        for c in out["cells"].values()
        if c["energy"] and not c["swapped"]
    ]
    idle = out["idle"]

    def pct(x: float) -> str:
        return f"{100 * x:.1f}\\%"

    def ci(t: tuple) -> str:
        return f"[{100 * t[0]:.1f}, {100 * t[1]:.1f}]"

    (GEN / "thresholds.tex").write_text(
        f"After the pilot and before confirmatory data we set $X={th['X']}$ and $Y={th['Y']}$ (protocol v1.1). "
        "The pilot showed large savings but also large accuracy losses for a naive cascade, so these are practical tolerances, not values chosen to make H3 pass. "
        "The policy tested under H3 is chosen on the validation split, then evaluated on test.\n"
    )
    (GEN / "rq1_text.tex").write_text(
        f"Table~\\ref{{tab:mac}} and Figure~\\ref{{fig:pareto}} summarise RQ1. Qwen2.5-7B (4-bit, GPU) was the most accurate configuration at {pct(big['accuracy'])} {ci(big['accuracy_ci'])} and cost "
        f"{big['joules_per_request_mean_over_domains']:.1f}\\,J of measured incremental energy per request. Qwen2.5-1.5B (4-bit, GPU) reached {pct(q15['accuracy'])} at "
        f"{q15['joules_per_request_mean_over_domains']:.1f}\\,J, about {big['joules_per_request_mean_over_domains'] / q15['joules_per_request_mean_over_domains']:.0f} times less energy for {100 * (big['accuracy'] - q15['accuracy']):.1f} points lower accuracy. "
        f"Mistral-7B (4-bit) scored {pct(s['mistral7b-q4|device']['accuracy'])}, indistinguishable from Qwen2.5-1.5B (paired difference {out['paired_accuracy']['mistral7b_minus_qwen1.5b_pts']:+.1f} points, 95\\% interval {out['paired_accuracy']['ci_pts'][0]:+.1f} to {out['paired_accuracy']['ci_pts'][1]:+.1f}), at an energy cost similar to Qwen2.5-7B. "
        f"The 0.5B models were close to chance on several subjects ({pct(q05['accuracy'])}). 8-bit quantisation did not improve accuracy over 4-bit at 1.5B "
        f"({pct(s['qwen1.5b-q8|device']['accuracy'])} vs {pct(q15['accuracy'])}) and did not cost more energy ({s['qwen1.5b-q8|device']['joules_per_request_mean_over_domains']:.1f} vs {q15['joules_per_request_mean_over_domains']:.1f}\\,J). "
        f"Domain matters: Qwen2.5-7B scored {pct(big['accuracy_by_domain']['general_control'])} on the general-science control but {pct(big['accuracy_by_domain']['healthcare'])} on healthcare, where Qwen2.5-1.5B did slightly better ({pct(q15['accuracy_by_domain']['healthcare'])}). "
        f"On the emulated CPU edge tier (4 of the chip's 10 CPU cores), the same 0.5B 4-bit model gave the same accuracy but took {e05['latency_median_s'] / q05['latency_median_s']:.1f} times longer per request (median {e05['latency_median_s'] * 1000:.0f} vs {q05['latency_median_s'] * 1000:.0f}\\,ms) and "
        f"{e05['joules_per_request_mean_over_domains'] / q05['joules_per_request_mean_over_domains']:.1f} times the energy: the 8-bit 0.5B model showed the same pattern, so on this laptop and with this thread count the GPU was both faster and more frugal than the CPU. "
        f"Idle power was {idle['w']:.2f}\\,W ({idle['first30_w']:.2f} and {idle['last30_w']:.2f}\\,W in the first and last 30\\,s), small against mean cell power of {min(pw):.0f} to {max(pw):.0f}\\,W, so the choice of idle window changes cell energy by at most {out['energy_sensitivity']['idle_window_max_abs_pct']:.1f}\\%. "
        f"Clock alignment matters more for short cells: power-sample timestamps have one-second resolution, and shifting them by half a second changes energy by up to {out['energy_sensitivity']['clock_shift_max_abs_pct_by_size']['qwen0.5b']:.1f}\\% for the 0.5B cells, {out['energy_sensitivity']['clock_shift_max_abs_pct_by_size']['qwen1.5b']:.1f}\\% for 1.5B and under {max(out['energy_sensitivity']['clock_shift_max_abs_pct_by_size']['qwen7b'], out['energy_sensitivity']['clock_shift_max_abs_pct_by_size']['mistral7b']) + 0.05:.0f}\\% for the 7B models. "
        f"{len(excl)} of {len(out['cells'])} cells recorded system-wide memory page-outs during the cell and are excluded from latency and energy by the pre-registered rule ({', '.join(e.split('__')[0] + ' ' + e.split('__')[1] + ' ' + e.split('__')[2].replace('_', ' ') for e in excl)}); their accuracy is kept. "
        f"Repeated timings were stable (median coefficient of variation {100 * statistics_median([v['median_cv'] for v in out['replay'].values() if v['median_cv'] is not None]):.1f}\\%).\n"
    )
    sv = out["sovereignty"]
    eq = sv["equal_weights"]
    (GEN / "sovereignty_text.tex").write_text(
        "We scored three options on six dimensions with an explicit rubric and cited evidence (\\texttt{configs/sovereignty\\_inputs.json}). "
        + "With equal weights the scores were "
        + "; ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in eq.items())
        + ". Across 5000 random weightings drawn uniformly from the simplex, the ranking never changed: "
        + ", ".join(f"{k.replace('_', ' ')} always ranked {int(sv['median_rank'][k])}" for k in eq)
        + ". The stability is itself a finding about the instrument, not only about the options: under this rubric the self-hosted options dominate the hosted API on every dimension, so no weighting can reverse them, and the two local options differ only in operational independence (a third-party conversion we could not verify). "
        "The rubric deliberately scores the deploying organisation's control, not the model publisher's jurisdiction; an organisation that weighs publisher origin would need an extra dimension, and then the EU-origin model could rank first. Making that choice explicit is the point of the instrument.\n"
    )
    cm = rt[h3["policy"]] if h3 and h3.get("policy") else None
    lr = rt["learned router"]
    tq = out["routing"]["tuned"]
    sd = out["routing"]["split_deltas_vs_big_pts"]
    wall = out["routing"]["h3_saving_pct_wall_time_apportioned"]
    a15 = rt["always qwen1.5b-q4"]
    (GEN / "routing_text.tex").write_text(
        "Routing energy is estimated, not measured: each item is priced at the measured mean energy per request of its configuration and domain, and a cascade pays for both models on escalated items. "
        f"Table~\\ref{{tab:routing}} reports all policies on the {out['routing']['split_counts']['test']} test items. "
        f"Always using Qwen2.5-1.5B saved {a15['energy_saving_vs_big_pct']:.0f}\\% of energy at {a15['accuracy_diff_vs_big_pts']:+.1f} points. "
        f"The confidence cascades and the learned router sat in between: the margin cascade saved {rt['cascade margin']['energy_saving_vs_big_pct']:.0f}\\% at {rt['cascade margin']['accuracy_diff_vs_big_pts']:+.1f} points, the $p_{{\\max}}$ cascade {rt['cascade p_max']['energy_saving_vs_big_pct']:.0f}\\% at {rt['cascade p_max']['accuracy_diff_vs_big_pts']:+.1f}, and the learned router {lr['energy_saving_vs_big_pct']:.0f}\\% at {lr['accuracy_diff_vs_big_pts']:+.1f}. "
        f"The tuned cascade thresholds were high ($\\tau={tq['cascade_p_max_tau']:.2f}$ and {tq['cascade_margin_tau']:.2f}), and the cascades escalated {100 * rt['cascade p_max']['escalation_rate']:.0f}\\% and {100 * rt['cascade margin']['escalation_rate']:.0f}\\% of test items, because the small model is often confidently wrong. "
        f"Compared with always using the small model, the cascades buy back about {rt['cascade margin']['accuracy_diff_vs_big_pts'] - a15['accuracy_diff_vs_big_pts']:.0f} points of accuracy for about {a15['energy_saving_vs_big_pct'] - rt['cascade margin']['energy_saving_vs_big_pct']:.0f} percentage points of the saving. "
        f"The constraint-aware optimiser chose Qwen2.5-7B in every domain: no cheaper single configuration stayed within {th['Y']} points of it on validation. "
        f"The static sensitivity rule, which keeps sensitive items on the EU-origin model, saved {rt['static sensitivity rule']['energy_saving_vs_big_pct']:.0f}\\% and lost {abs(rt['static sensitivity rule']['accuracy_diff_vs_big_pts']):.1f} points: here sovereignty preferences cost accuracy rather than energy. "
        f"An oracle that knew which model would be right reached {pct(rt['oracle (upper bound, uses labels)']['accuracy'])} at {rt['oracle (upper bound, uses labels)']['energy_saving_vs_big_pct']:.0f}\\% saving; it is unattainable, but it shows the headroom that better confidence signals could unlock.\n\n"
        + (
            f"\\textbf{{H3.}} The learned router's weights were fit on train; every threshold was tuned on validation, and the H3 policy was then selected on the same validation split, so validation was used twice and test once. "
            f"Selected this way, the {h3['policy'].replace('_', chr(92) + '_')} policy saved {h3['test_saving_pct']:.1f}\\% of estimated energy per request on test (95\\% interval {h3['test_saving_pct_ci'][0]:.0f} to {h3['test_saving_pct_ci'][1]:.0f}\\%) "
            f"with an accuracy change of {h3['test_accuracy_diff_pts']:+.1f} points [{h3['test_accuracy_diff_ci_pts'][0]:+.1f}, {h3['test_accuracy_diff_ci_pts'][1]:+.1f}]. "
            + (
                "Both point estimates meet the thresholds set before confirmatory data, so H3 is supported on point estimates. "
                if h3["supported_on_point_estimates"]
                else "H3 is not supported. "
            )
            + (
                ""
                if h3["accuracy_ci_within_tolerance"] and h3["energy_ci_meets_X"]
                else f"Neither interval clears its threshold: the saving interval reaches below {th['X']}\\% and the accuracy interval past the {th['Y']}-point tolerance. "
            )
            + f"Two further checks point the same way. The test split appears easier for the small model than the others (relative to Qwen2.5-7B, always Qwen2.5-1.5B scored {sd['always qwen1.5b-q4']['train']:+.1f}, {sd['always qwen1.5b-q4']['val']:+.1f} and {sd['always qwen1.5b-q4']['test']:+.1f} points on train, validation and test; the selected cascade {sd[h3['policy']]['train']:+.1f}, {sd[h3['policy']]['val']:+.1f} and {sd[h3['policy']]['test']:+.1f}), so the test loss is probably an underestimate. "
            + f"And if each cell's energy is apportioned by item wall time instead of evenly, the saving becomes {wall:.1f}\\%. "
            + "We therefore read H3 as tentative support at best, and as a calibrated estimate of what this kind of cascade is worth rather than a confirmed effect."
            if cm
            else "\\textbf{H3.} No non-oracle policy met the accuracy tolerance on validation."
        )
        + "\n"
    )
    (GEN / "abstract_results.tex").write_text(
        f"Qwen2.5-7B on the GPU was most accurate ({pct(big['accuracy'])}) at {big['joules_per_request_mean_over_domains']:.1f}\\,J of measured incremental energy per request; Qwen2.5-1.5B gave {pct(q15['accuracy'])} at {q15['joules_per_request_mean_over_domains']:.1f}\\,J, and Mistral-7B matched the 1.5B model's accuracy at the 7B energy cost. "
        "On this laptop the CPU tier was slower and used more energy than the GPU for the same small model. "
        f"A margin-based cascade, chosen on validation, saved an estimated {h3['test_saving_pct']:.0f}\\% of energy on held-out items at {h3['test_accuracy_diff_pts']:+.1f} accuracy points, meeting the thresholds on point estimates, but both intervals cross their thresholds, so support is tentative. "
        "Under our rubric, self-hosted options dominated a hosted EU API on every weighting.%"
    )
    esc = 100 * rt["cascade margin"]["escalation_rate"]
    (GEN / "discussion.tex").write_text(
        "\\textbf{What an SME can take from this.} On one laptop, the choice of model moved energy per request by more than an order of magnitude "
        f"({min(v['joules_per_request_mean_over_domains'] for v in s.values() if v['joules_per_request_mean_over_domains']):.1f} to {max(v['joules_per_request_mean_over_domains'] for v in s.values() if v['joules_per_request_mean_over_domains']):.1f}\\,J across configuration means) while moving accuracy by tens of points, and the two did not move together in a simple way: "
        "the EU-origin 7B model cost as much as the most accurate model but was no more accurate than a model a fifth of its size. "
        "Measured energy, not parameter count, is what separates these options. Placement mattered too: moving the 0.5B models from the laptop GPU to four CPU cores, a stand-in for a modest on-premise server, made them slower and costlier at the same accuracy. "
        "``Running it at the edge'' is therefore not automatically the frugal choice; it depends on the hardware the edge actually has.\n\n"
        "\\textbf{Why routing helped only modestly.} Routing pays off when a cheap model knows when it is likely to be wrong. "
        f"Here the small model was often confidently wrong, so to stay near the large model's accuracy the margin cascade had to escalate {esc:.0f}\\% of items and still pay for the small model on each of them, and its estimated saving shrank from the {a15['energy_saving_vs_big_pct']:.0f}\\% the small model alone offers to {rt['cascade margin']['energy_saving_vs_big_pct']:.0f}\\%. "
        "The gap between the cascades and the oracle shows where the leverage is: better confidence estimation, task-aware routing features or a verifier would convert more of that headroom into savings \\cite{guo2017,kadavath2022,hybridllm}. "
        "For an SME the practical reading is that routing is worth a meaningful fraction of energy, not most of it, at today's small-model calibration, and that simply using the small model may be the better trade when a few points of accuracy are affordable.\n\n"
        "\\textbf{Sovereignty as a design decision.} The scorecard's stable ranking came from the rubric, not from the data: once self-hosting is scored as the organisation's own control, every local option beats any hosted one regardless of weights, and the EU-origin model is not favoured. "
        "A different organisation could reasonably score publisher jurisdiction, training-data transparency or supply-chain origin more finely and reach a different ranking. "
        "We think this is the right way to use such an instrument: as a transparent statement of which dimensions an organisation chooses to value, with evidence attached, rather than as a single objective number. "
        "The static sensitivity rule makes the trade-off concrete: honouring a preference for an EU-origin model on sensitive items cost accuracy without saving much energy.\n\n"
        "\\textbf{What one laptop cannot show.} The continuum in this study is short: one GPU, its own CPU and a documented but unexecuted cloud tier. "
        "The figures say nothing about data-centre efficiency, batching servers or network energy, and the edge tier shares the chip with the device tier. "
        "The contribution is a method and a calibrated first data point that a larger study can extend to real edge hardware and hosted tiers.\n"
    )


def appendix(out: dict) -> None:
    """Appendix tables: per-domain accuracy and per-cell energy with sensitivity."""
    s, cells = out["summary"], out["cells"]
    doms = ["healthcare", "digital_industries", "general_control"]
    lines = [
        r"\begin{table}[h]\centering\footnotesize",
        r"\caption{Accuracy (\%) by domain and configuration, 150 items per domain.}\label{tab:domain}",
        r"\begin{tabular}{@{}llrrr@{}}\toprule",
        r"Config & Tier & Health & Digital ind. & Control\\\midrule",
    ]
    for k, v in s.items():
        cfg, tier = k.split("|")
        lines.append(
            f"{cfg} & {tier} & "
            + " & ".join(f"{100 * v['accuracy_by_domain'][d]:.1f}" for d in doms)
            + r"\\"
        )
    lines.append(r"\bottomrule\end{tabular}\end{table}")
    lines += [
        r"\begin{table}[h]\centering\footnotesize",
        r"\caption{Energy per request (J) by cell, with the idle-window alternatives (first and last 30\,s of the baseline). Swapped cells are excluded.}\label{tab:cells}",
        r"\begin{tabular}{@{}lrrrr@{}}\toprule",
        r"Cell & Power (W) & J/req & idle first & idle last\\\midrule",
    ]
    for stem, c in sorted(cells.items()):
        e = c["energy"]
        name = f"{c['config']} {c['tier'][0]} {c['domain'][:4]}"
        if not e or c["swapped"]:
            lines.append(f"{name} & \\multicolumn{{4}}{{c}}{{excluded (page-outs)}}\\\\")
            continue
        lines.append(
            f"{name} & {e['mean_power_w']:.1f} & {e['joules_per_request']:.2f} & {e['joules_per_request_idle_first30']:.2f} & {e['joules_per_request_idle_last30']:.2f}\\\\"
        )
    lines.append(r"\bottomrule\end{tabular}\end{table}")
    (GEN / "appendix_tables.tex").write_text("\n".join(lines) + "\n")


def explorer(out: dict) -> None:
    """Static results explorer for the docs site: sortable table, provenance on hover."""
    rows = []
    for k, v in out["summary"].items():
        cfg, tier = k.split("|")
        j = v["joules_per_request_mean_over_domains"]
        prov = (
            "measured on the M1 Max GPU"
            if tier == "device"
            else "measured on the Mac CPU; edge tier emulated"
        )
        rows.append(
            f"<tr><td>{cfg}</td><td>{tier}</td><td title='450 items, bootstrap 95% CI {100 * v['accuracy_ci'][0]:.1f} to {100 * v['accuracy_ci'][1]:.1f}'>{100 * v['accuracy']:.1f}</td>"
            f"<td title='median per-request wall time'>{1000 * v['latency_median_s']:.0f}</td>"
            f"<td title='{prov}; idle {out['idle']['w']:.2f} W subtracted'>{'excluded' if j is None else f'{j:.2f}'}</td></tr>"
        )
    for name, r in out["routing"]["policies"].items():
        rows.append(
            f"<tr><td>{name}</td><td>policy (test, 135 items)</td><td title='paired difference vs always qwen7b-q4: {r['accuracy_diff_vs_big_pts']:+.1f} pts'>{100 * r['accuracy']:.1f}</td>"
            f"<td title='sum of per-item latencies along the routing path'>{1000 * r['latency_mean_s']:.0f}</td>"
            f"<td title='estimated: replay of measured per-cell energy; no routed run'>{r.get('joules_mean', float('nan')):.2f}</td></tr>"
        )
    html = (
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContinuumBench explorer</title><style>
body{font:15px system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#17242b;background:#fff}
table{border-collapse:collapse;width:100%}th,td{padding:6px 8px;border-bottom:1px solid #d6dde1;text-align:left}
th{cursor:pointer;background:#f5f7f8}td[title]{text-decoration:underline dotted}
@media (prefers-color-scheme:dark){body{background:#11181c;color:#e4ecef}th{background:#182227}th,td{border-color:#2c3a41}}
</style></head><body><h1>ContinuumBench explorer</h1>
<p>Generated by <code>scripts/analyze_mac.py</code>. Click a header to sort. Hover a value to see its provenance. Energy is joules per request; latency is milliseconds.</p>
<table id="t"><thead><tr><th>Configuration or policy</th><th>Tier / set</th><th>Accuracy (%)</th><th>Latency (ms)</th><th>Energy (J)</th></tr></thead><tbody>
"""
        + "\n".join(rows)
        + """
</tbody></table><p><a href="results/">Results</a> &middot; <a href="method/">Method</a></p>
<script>document.querySelectorAll('th').forEach((h,i)=>h.onclick=()=>{const b=document.querySelector('tbody');const r=[...b.rows];const d=h.dataset.d=h.dataset.d==='a'?'d':'a';r.sort((x,y)=>{const p=x.cells[i].textContent,q=y.cells[i].textContent;const a=parseFloat(p),c=parseFloat(q);const v=isNaN(a)||isNaN(c)?p.localeCompare(q):a-c;return d==='a'?v:-v});r.forEach(t=>b.appendChild(t))})</script>
</body></html>
"""
    )
    (root / "docs/explorer.html").write_text(html)


def statistics_median(v: list[float]) -> float:
    return st.median(v) if v else float("nan")


def readme_block(out: dict) -> None:
    """Rewrite the generated results block in README.md and docs/results.md from `out`."""
    s, h3 = out["summary"], out["routing"]["H3"]
    rows = [
        "| Configuration | Tier | Accuracy (95% CI) | Median latency | Energy per request |",
        "| :--- | :--- | ---: | ---: | ---: |",
    ]
    for k, v in sorted(s.items(), key=lambda kv: -kv[1]["accuracy"]):
        cfg, tier = k.split("|")
        j = v["joules_per_request_mean_over_domains"]
        jtxt = "excluded (swap)" if j is None else f"{j:.1f} J"
        nx = len(v["latency_domains_excluded"])
        ltxt = f"{1000 * v['latency_median_s']:.0f} ms" + (
            f" ({3 - nx} of 3 domains)" if nx else ""
        )
        rows.append(
            f"| {cfg} | {tier} | {100 * v['accuracy']:.1f}% ({100 * v['accuracy_ci'][0]:.1f} to {100 * v['accuracy_ci'][1]:.1f}) | {ltxt} | {jtxt} |"
        )
    lines = [
        "<!-- results:start (generated by scripts/analyze_mac.py; do not edit by hand) -->",
        f"**Routing (H3).** Chosen on validation, the `{h3['policy']}` policy saved an estimated **{h3['test_saving_pct']:.0f}%** of energy per request (95% CI {h3['test_saving_pct_ci'][0]:.0f} to {h3['test_saving_pct_ci'][1]:.0f}%) on {out['routing']['split_counts']['test']} held-out items at **{h3['test_accuracy_diff_pts']:+.1f} accuracy points** (95% CI {h3['test_accuracy_diff_ci_pts'][0]:+.1f} to {h3['test_accuracy_diff_ci_pts'][1]:+.1f}) versus always using Qwen2.5-7B. "
        + (
            f"That meets the thresholds set before confirmatory data (at least {out['thresholds']['X']}% saved, at most {out['thresholds']['Y']} points lost) on point estimates, but both intervals cross their thresholds, the test split looks easier for the small model than validation, and apportioning energy by item time gives {out['routing']['h3_saving_pct_wall_time_apportioned']:.1f}%. Support is tentative at best."
            if h3["supported_on_point_estimates"]
            else "That does not meet the thresholds."
        )
        + " Routing energy is estimated by replaying measured per-cell energy over each policy's choices; no routed run was executed.",
        "",
        *rows,
        "",
        f"Energy is measured incremental CPU+GPU+ANE energy from `powermetrics` on one M1 Max (idle {out['idle']['w']:.2f} W subtracted). The edge tier is the same Mac's CPU, an emulation of a small server. Cells with system-wide memory page-outs during the run are excluded from latency and energy.",
        "<!-- results:end -->",
    ]
    block = "\n".join(lines)
    readme = root / "README.md"
    txt = readme.read_text()
    a, b = "<!-- results:start", "<!-- results:end -->"
    if a in txt and b in txt:
        i, j = txt.index(a), txt.index(b) + len(b)
        readme.write_text(txt[:i] + block + txt[j:])
    (root / "docs/results.md").write_text(
        "# Results\n\n"
        + block
        + "\n\nThe full report is in [`paper/report.pdf`](https://github.com/Agent007repo/continuum-bench/blob/main/paper/report.pdf). Every number here is regenerated by `make analyze` from the raw records in `results/mac/`.\n"
    )


if __name__ == "__main__":
    main()
