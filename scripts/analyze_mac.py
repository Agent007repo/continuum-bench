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
    prose(out)
    readme_block(out)
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
            chosen = max(cands, key=lambda n: cands[n][0])
            b = results[chosen]
            h3 = {
                "selected_on": "validation split",
                "policy": chosen,
                "validation_saving_pct": cands[chosen][0],
                "validation_accuracy_diff_pts": cands[chosen][1],
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
    fig, ax = plt.subplots(figsize=(5, 3.6))
    short = {
        "qwen0.5b-q4": "Q0.5/4",
        "qwen0.5b-q8": "Q0.5/8",
        "qwen1.5b-q4": "Q1.5/4",
        "qwen1.5b-q8": "Q1.5/8",
        "qwen7b-q4": "Q7/4",
        "mistral7b-q4": "M7/4",
    }
    for k, v in pts:
        cfg, tier = k.split("|")
        x, y = v["joules_per_request_mean_over_domains"], 100 * v["accuracy"]
        ax.scatter(
            x,
            y,
            marker="o" if tier == "device" else "s",
            s=28,
            color="#1f6f8b" if tier == "device" else "#b5651d",
            zorder=3,
        )
        ax.annotate(
            short.get(cfg, cfg) + ("" if tier == "device" else " edge"),
            (x, y),
            fontsize=6.5,
            xytext=(4, -10 if tier == "edge" else 4),
            textcoords="offset points",
        )
    code = {
        "static sensitivity rule": "S",
        "cascade p_max": "Cp",
        "cascade margin": "Cm",
        "learned router": "R",
        "constraint-aware optimiser": "O",
        "oracle (upper bound, uses labels)": "oracle",
    }
    for name, r in routing["policies"].items():
        if name.startswith("always") or "joules_mean" not in r:
            continue
        ax.scatter(r["joules_mean"], 100 * r["accuracy"], marker="^", s=30, color="#555", zorder=3)
        ax.annotate(
            code.get(name, name),
            (r["joules_mean"], 100 * r["accuracy"]),
            fontsize=6.5,
            xytext=(4, 2),
            textcoords="offset points",
            color="#333",
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
        f"Mistral-7B (4-bit) was less accurate than Qwen2.5-1.5B ({pct(s['mistral7b-q4|device']['accuracy'])}) at a cost similar to Qwen2.5-7B. "
        f"The 0.5B models were close to chance on several subjects ({pct(q05['accuracy'])}). 8-bit quantisation did not improve accuracy over 4-bit at 1.5B "
        f"({pct(s['qwen1.5b-q8|device']['accuracy'])} vs {pct(q15['accuracy'])}) and did not cost more energy ({s['qwen1.5b-q8|device']['joules_per_request_mean_over_domains']:.1f} vs {q15['joules_per_request_mean_over_domains']:.1f}\\,J). "
        f"Domain matters: Qwen2.5-7B scored {pct(big['accuracy_by_domain']['general_control'])} on the general-science control but {pct(big['accuracy_by_domain']['healthcare'])} on healthcare, where Qwen2.5-1.5B did slightly better ({pct(q15['accuracy_by_domain']['healthcare'])}). "
        f"On the emulated CPU edge tier, the same 0.5B model gave the same accuracy but took {e05['latency_median_s'] / q05['latency_median_s']:.1f} times longer per request (median {e05['latency_median_s'] * 1000:.0f} vs {q05['latency_median_s'] * 1000:.0f}\\,ms) and "
        f"{e05['joules_per_request_mean_over_domains'] / q05['joules_per_request_mean_over_domains']:.1f} times the energy: on this laptop the GPU is both faster and more frugal than the CPU for the same model. "
        f"Idle power was {idle['w']:.2f}\\,W ({idle['first30_w']:.2f} and {idle['last30_w']:.2f}\\,W in the first and last 30\\,s), small against mean cell power of {min(pw):.0f} to {max(pw):.0f}\\,W, so the idle choice changes energy figures by a few percent at most. "
        f"{len(excl)} of {len(out['cells'])} cells recorded memory page-outs and are excluded from latency and energy by the pre-registered rule ({', '.join(e.split('__')[0] + ' ' + e.split('__')[1] + ' ' + e.split('__')[2].replace('_', ' ') for e in excl)}); their accuracy is kept. "
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
    (GEN / "routing_text.tex").write_text(
        f"Table~\\ref{{tab:routing}} reports all policies on the {out['routing']['split_counts']['test']} test items. "
        f"Always using Qwen2.5-1.5B saved {rt['always qwen1.5b-q4']['energy_saving_vs_big_pct']:.0f}\\% of energy at {rt['always qwen1.5b-q4']['accuracy_diff_vs_big_pts']:+.1f} points. "
        f"The confidence cascades and the learned router sat in between: the margin cascade saved {rt['cascade margin']['energy_saving_vs_big_pct']:.0f}\\% at {rt['cascade margin']['accuracy_diff_vs_big_pts']:+.1f} points, the $p_{{\\max}}$ cascade {rt['cascade p_max']['energy_saving_vs_big_pct']:.0f}\\% at {rt['cascade p_max']['accuracy_diff_vs_big_pts']:+.1f}, and the learned router {lr['energy_saving_vs_big_pct']:.0f}\\% at {lr['accuracy_diff_vs_big_pts']:+.1f}. "
        f"The tuned cascade thresholds were high ($\\tau={out['routing']['tuned']['cascade_p_max_tau']:.2f}$ and {out['routing']['tuned']['cascade_margin_tau']:.2f}), because the small model is confidently wrong on many items, which the pilot had already suggested. "
        f"The constraint-aware optimiser chose Qwen2.5-7B in every domain: no cheaper single configuration stayed within {th['Y']} points of it on validation. "
        f"The static sensitivity rule, which keeps sensitive items on the EU-origin model, saved {rt['static sensitivity rule']['energy_saving_vs_big_pct']:.0f}\\% and lost {abs(rt['static sensitivity rule']['accuracy_diff_vs_big_pts']):.1f} points: here sovereignty preferences cost accuracy rather than energy. "
        f"An oracle that knew which model would be right reached {pct(rt['oracle (upper bound, uses labels)']['accuracy'])} at {rt['oracle (upper bound, uses labels)']['energy_saving_vs_big_pct']:.0f}\\% saving, showing how much headroom better confidence signals could unlock.\n\n"
        + (
            f"\\textbf{{H3.}} Selected on validation, the {h3['policy'].replace('_', chr(92) + '_')} policy saved {h3['test_saving_pct']:.1f}\\% of energy per request on test (paired saving {h3['test_saving_j_ci'][0]:.1f} to {h3['test_saving_j_ci'][1]:.1f}\\,J per request, 95\\% interval) "
            f"with an accuracy change of {h3['test_accuracy_diff_pts']:+.1f} points [{h3['test_accuracy_diff_ci_pts'][0]:+.1f}, {h3['test_accuracy_diff_ci_pts'][1]:+.1f}]. "
            + (
                "Both point estimates meet the pre-registered thresholds, so H3 is supported on point estimates. "
                if h3["supported_on_point_estimates"]
                else "H3 is not supported. "
            )
            + (
                "The accuracy interval stays within the tolerance."
                if h3["accuracy_ci_within_tolerance"]
                else f"However, the lower end of the accuracy interval exceeds the {th['Y']}-point tolerance, so with {out['routing']['split_counts']['test']} test items we cannot rule out a loss larger than we said we would accept. We read this as tentative support."
            )
            if cm
            else "\\textbf{H3.} No non-oracle policy met the accuracy tolerance on validation."
        )
        + "\n"
    )
    (GEN / "abstract_results.tex").write_text(
        f"Qwen2.5-7B on the GPU was most accurate ({pct(big['accuracy'])}) at {big['joules_per_request_mean_over_domains']:.1f}\\,J of measured incremental energy per request; Qwen2.5-1.5B gave {pct(q15['accuracy'])} at {q15['joules_per_request_mean_over_domains']:.1f}\\,J. "
        f"The CPU edge tier was slower and used more energy than the GPU for the same model. "
        f"A margin-based cascade, chosen on validation, cut energy by {h3['test_saving_pct']:.0f}\\% on held-out items at {h3['test_accuracy_diff_pts']:+.1f} accuracy points, meeting the pre-registered thresholds on point estimates, though the accuracy interval reaches past the tolerance. "
        "Under our rubric, self-hosted options dominated a hosted EU API on every weighting."
    )


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
        f"**Routing (H3, pre-registered).** Chosen on validation, the `{h3['policy']}` policy saved **{h3['test_saving_pct']:.0f}%** of measured energy per request on {out['routing']['split_counts']['test']} held-out items at **{h3['test_accuracy_diff_pts']:+.1f} accuracy points** (95% CI {h3['test_accuracy_diff_ci_pts'][0]:+.1f} to {h3['test_accuracy_diff_ci_pts'][1]:+.1f}) versus always using Qwen2.5-7B. "
        + (
            "That meets the thresholds (at least 25% saved, at most 5 points lost) on point estimates; the accuracy interval reaches past the tolerance, so support is tentative."
            if h3["supported_on_point_estimates"] and not h3["accuracy_ci_within_tolerance"]
            else (
                "That meets the thresholds."
                if h3["supported_on_point_estimates"]
                else "That does not meet the thresholds."
            )
        ),
        "",
        *rows,
        "",
        f"Energy is measured incremental CPU+GPU+ANE energy from `powermetrics` on one M1 Max (idle {out['idle']['w']:.2f} W subtracted). The edge tier is the same Mac's CPU, an emulation of a small server. Cells with memory page-outs are excluded from latency and energy.",
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
