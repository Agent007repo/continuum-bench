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


def power_samples() -> list[dict]:
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
    offset = st.median(s["hdr"] - s["cum"] for s in samples) + 0.5
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
        lat = [r["wall_s"] for r in rs]
        cs = [c for c in cells.values() if (c["config"], c["tier"]) == k]
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
        "sovereignty": sov,
        "thresholds": thresholds,
    }
    (D / "mac_summary.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    figures(summary, routing)
    tex(out)
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
    chosen = {}
    for d in doms:
        vids = [i for i in items if split[i] == "val" and dom_of[i] == d]
        bigacc = st.mean(1.0 if table[(big, i)]["correct"] else 0.0 for i in vids)
        cands = []
        for c in configs:
            a = st.mean(1.0 if table[(c, i)]["correct"] else 0.0 for i in vids)
            cost = st.mean((energy(c, i) if have_energy else lat(c, i)) for i in vids)
            if a >= bigacc - floor_drop:
                cands.append((cost, c))
        chosen[d] = min(cands)[1] if cands else big
    policies["constraint-aware optimiser"] = {i: [chosen[dom_of[i]]] for i in items}

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
    for r in results.values():
        if have_energy:
            r["energy_saving_vs_big_pct"] = 100 * (1 - r["joules_mean"] / base["joules_mean"])
            diffs = [b - a for a, b in zip(r["paired"]["j"], base["paired"]["j"], strict=True)]
            r["saving_j_ci"] = boot_ci(diffs)
        dacc = [a - b for a, b in zip(r["paired"]["acc"], base["paired"]["acc"], strict=True)]
        r["accuracy_diff_vs_big_pts"] = 100 * st.mean(dacc)
        r["accuracy_diff_ci_pts"] = tuple(100 * x for x in boot_ci(dacc))
        r.pop("paired")
    h3 = None
    if thresholds.get("X") is not None and have_energy:
        cand = {
            k: v for k, v in results.items() if not k.startswith("always") and "oracle" not in k
        }
        best_name = max(
            cand,
            key=lambda k: (
                cand[k]["energy_saving_vs_big_pct"]
                if cand[k]["accuracy_diff_vs_big_pts"] >= -thresholds["Y"]
                else -1e9
            ),
        )
        b = cand[best_name]
        h3 = {
            "policy": best_name,
            "saving_pct": b["energy_saving_vs_big_pct"],
            "accuracy_diff_pts": b["accuracy_diff_vs_big_pts"],
            "accuracy_diff_ci_pts": b["accuracy_diff_ci_pts"],
            "supported": b["energy_saving_vs_big_pct"] >= thresholds["X"]
            and b["accuracy_diff_vs_big_pts"] >= -thresholds["Y"],
        }
    return {
        "split_counts": {s: sum(v == s for v in split.values()) for s in ("train", "val", "test")},
        "tuned": {
            "cascade_p_max_tau": tau_p,
            "cascade_margin_tau": tau_m,
            "router_threshold": th_lr,
            "optimiser_choice": chosen,
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
    fig, ax = plt.subplots(figsize=(5, 3.4))
    for k, v in pts:
        cfg, tier = k.split("|")
        ax.scatter(
            v["joules_per_request_mean_over_domains"],
            100 * v["accuracy"],
            marker="o" if tier == "device" else "s",
            color="#1f6f8b" if tier == "device" else "#b5651d",
        )
        ax.annotate(
            f"{cfg} ({tier})",
            (v["joules_per_request_mean_over_domains"], 100 * v["accuracy"]),
            fontsize=6,
            xytext=(3, 3),
            textcoords="offset points",
        )
    for name, r in routing["policies"].items():
        if name.startswith("always") or "joules_mean" not in r:
            continue
        ax.scatter(r["joules_mean"], 100 * r["accuracy"], marker="^", color="#444")
        ax.annotate(
            name,
            (r["joules_mean"], 100 * r["accuracy"]),
            fontsize=6,
            xytext=(3, -8),
            textcoords="offset points",
        )
    ax.set_xscale("log")
    ax.set_xlabel("Measured incremental energy per request (J, log scale)")
    ax.set_ylabel("Accuracy (%)")
    ax.grid(alpha=0.3)
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
        r"\begin{table}[t]\centering\small",
        r"\caption{Routing policies on the held-out test split, device tier.}\label{tab:routing}",
        r"\begin{tabular}{@{}lrrr@{}}\toprule",
        r"Policy & Acc. & $\Delta$acc (pts) & Energy saving\\\midrule",
    ]
    for name, r in rt.items():
        sav = r.get("energy_saving_vs_big_pct")
        lines.append(
            f"{name} & {100 * r['accuracy']:.1f} & {r['accuracy_diff_vs_big_pts']:+.1f} & {'n/a' if sav is None else f'{sav:.0f}\\%'}\\\\"
        )
    lines.append(r"\bottomrule\end{tabular}\end{table}")
    (GEN / "routing_table.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
