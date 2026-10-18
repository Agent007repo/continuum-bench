"""Live validation of the H3 routing policy on the Mac (device tier).

Loads Qwen2.5-1.5B (4-bit) and Qwen2.5-7B (4-bit) on the GPU at the same time and runs the
135 test items under two policies, alternating in blocks so that drift affects both equally:

  A  always Qwen2.5-7B
  B  margin cascade: Qwen2.5-1.5B first; escalate to 7B when its label margin is below tau

tau is the value tuned on validation and recorded in results/derived/mac_summary.json
(routing.tuned.cascade_margin_tau), so nothing here is tuned on test. Each block records
its epoch window; powermetrics runs alongside and analysis integrates power over each
window. Unlike the offline replay, this measures the real energy of routing, including
running both models and switching between them.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_run import Scorer, one, pageouts, sh, sha256  # noqa: E402

SEED = 20261017


def split_of(item_ids: list[str]) -> dict[str, str]:
    """Same split as scripts/analyze_mac.py: train 50, validation 20, test 30 per domain."""
    out: dict[str, str] = {}
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol", type=Path, default=Path("configs/2026-10-17-mac-v1.json"))
    ap.add_argument("--items", type=Path, default=Path("data/items/items-v1.jsonl"))
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--tau", type=float, required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from llama_cpp import Llama

    proto = json.loads(args.protocol.read_text())
    tier = proto["tiers"]["device"]
    items = [json.loads(x) for x in args.items.read_text().splitlines() if x]
    conf = [i for i in items if i["phase"] == "confirmatory"]
    split = split_of([i["id"] for i in conf])
    test = [i for i in conf if split[i["id"]] == "test"]

    def load(cfg_id: str):
        cfg = next(c for c in proto["configurations"] if c["id"] == cfg_id)
        f = args.models_dir / cfg["files"][0]
        for name in cfg["files"]:
            if sha256(args.models_dir / name) != cfg["sha256"][name]:
                raise SystemExit(f"checksum mismatch for {name}")
        llm = Llama(
            model_path=str(f),
            n_ctx=proto["runtime"]["n_ctx"],
            n_threads=tier["threads"],
            n_threads_batch=tier["threads"],
            n_batch=proto["runtime"]["n_batch"],
            n_gpu_layers=tier["n_gpu_layers"],
            seed=0,
            verbose=False,
        )
        return Scorer(llm)

    small, big = load("qwen1.5b-q4"), load("qwen7b-q4")
    args.out.mkdir(parents=True, exist_ok=True)

    def run_always_big() -> list[dict]:
        return [
            {"policy": "always qwen7b-q4", "path": ["qwen7b-q4"], **one(big, it)} for it in test
        ]

    def run_cascade() -> list[dict]:
        rows = []
        for it in test:
            r = one(small, it)
            if r["margin"] >= args.tau:
                rows.append({"policy": "cascade margin", "path": ["qwen1.5b-q4"], **r})
            else:
                r2 = one(big, it)
                r2["t_start_epoch"], r2["small_margin"] = r["t_start_epoch"], r["margin"]
                r2["wall_s"] = round(r["wall_s"] + r2["wall_s"], 6)
                rows.append(
                    {"policy": "cascade margin", "path": ["qwen1.5b-q4", "qwen7b-q4"], **r2}
                )
        return rows

    # warm-up on 10 items, both models, discarded
    for it in test[:10]:
        one(small, it)
        one(big, it)

    blocks = []
    po0, therm0 = pageouts(), sh(["pmset", "-g", "therm"])
    for rnd in range(args.rounds):
        for name, fn in (("A", run_always_big), ("B", run_cascade)):
            t0 = time.time()
            rows = fn()
            t1 = time.time()
            path = args.out / f"live_r{rnd}_{name}.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            acc = sum(r["correct"] for r in rows) / len(rows)
            esc = sum(len(r["path"]) > 1 for r in rows) / len(rows)
            blocks.append(
                {
                    "round": rnd,
                    "block": name,
                    "policy": rows[0]["policy"],
                    "window_epoch": [round(t0, 6), round(t1, 6)],
                    "n": len(rows),
                    "accuracy": acc,
                    "escalation_rate": esc,
                    "rows": path.name,
                }
            )
            print(json.dumps(blocks[-1]), flush=True)
    po1 = pageouts()
    (args.out / "live_manifest.json").write_text(
        json.dumps(
            {
                "identity": "ContinuumBench/mac/live-routing/2026-10-18",
                "tau": args.tau,
                "n_test_items": len(test),
                "rounds": args.rounds,
                "blocks": blocks,
                "pageouts_before": po0,
                "pageouts_after": po1,
                "swapped": po0 is not None and po1 is not None and po1 > po0,
                "thermal_before": therm0,
            },
            indent=1,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
