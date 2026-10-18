"""Run one benchmark cell (model configuration x tier x domain shard) and write raw records.

Runs on the Mac named in the protocol (llama-cpp-python built for Metal). Each item gets one forward pass over the model's chat-formatted prompt. The answer is the
label with the highest probability mass among the top-20 next-token log probabilities,
so quality is scored automatically against the dataset's published label. We record wall
time, wall-clock start and end (epoch seconds, for alignment with powermetrics), process
CPU time (all threads), prompt tokens and peak resident memory. Energy is measured
separately by powermetrics; this script writes the cell windows that analysis integrates
over. Swap activity (vm_stat page-outs) and thermal state (pmset) are recorded per cell.

After the main pass, a fixed timing subset is replayed: 3 warm-up passes (discarded),
then 5 measured repetitions.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

SYSTEM = {
    "mc": "You answer multiple-choice questions. Reply with the letter of the correct option only.",
    "ynm": "You answer biomedical research questions from the given abstract. Reply with one word: yes, no or maybe.",
}
TIMING_SUBSET = 10
WARMUP, REPS = 3, 5


def prompt_for(item: dict) -> tuple[list[dict], str]:
    """One user message holding the instruction and the question, for every model.

    Mistral-7B-Instruct-v0.3's embedded chat template rejects a separate system role
    (observed in the Mac pilot), so all models get the same single-turn layout."""
    if item["source"] == "pubmedqa":
        user = f"Abstract: {item['context']}\n\nQuestion: {item['question']}\nAnswer (yes, no or maybe):"
        return [{"role": "user", "content": SYSTEM["ynm"] + "\n\n" + user}], "ynm"
    opts = "\n".join(
        f"{lab}. {txt}" for lab, txt in zip(item["labels"], item["choices"], strict=True)
    )
    user = f"Question: {item['question']}\n{opts}\nAnswer:"
    return [{"role": "user", "content": SYSTEM["mc"] + "\n\n" + user}], "mc"


def label_mass(top: list[dict], labels: list[str]) -> dict[str, float]:
    """Sum first-token probability per label. A token maps to a label when its stripped,
    lower-cased text is a non-empty prefix of exactly one label."""
    lows = [lab.lower() for lab in labels]
    mass = dict.fromkeys(labels, 0.0)
    for t in top:
        tok = t["token"].strip().lower().rstrip(".:)")
        if not tok:
            continue
        hits = [i for i, lab in enumerate(lows) if lab.startswith(tok)]
        if len(hits) == 1:
            mass[labels[hits[0]]] += math.exp(t["logprob"])
    return mass


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def pageouts() -> int | None:
    for line in sh(["vm_stat"]).splitlines():
        if line.startswith("Pageouts:"):
            return int(line.split(":")[1].strip().rstrip("."))
    return None


def cpu_info() -> dict:
    info = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "nproc": os.cpu_count(),
    }
    if platform.system() == "Darwin":
        info["cpu_model"] = sh(["sysctl", "-n", "machdep.cpu.brand_string"])
        info["mem_total_bytes"] = int(sh(["sysctl", "-n", "hw.memsize"]) or 0)
        info["macos"] = sh(["sw_vers", "-productVersion"])
        info["hw_model"] = sh(["sysctl", "-n", "hw.model"])
        return info
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
        mem = Path("/proc/meminfo").read_text().splitlines()[0]
        info["mem_total_kb"] = int(mem.split()[1])
    except OSError:
        pass
    return info


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


class Scorer:
    """First-token distribution from one forward pass over the model's own chat template.

    Equivalent to the first sampled position of a chat completion, without keeping
    logits for every position (llama-cpp-python requires logits_all for logprobs,
    which would add over 1 GB per model)."""

    def __init__(self, llm) -> None:
        import llama_cpp
        import numpy as np
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter

        self.llm, self.np, self.llama_cpp = llm, np, llama_cpp
        meta = llm.metadata
        vocab = llm._model
        eos = llm.detokenize([vocab.token_eos()]).decode("utf-8", "ignore")
        bos = (
            llm.detokenize([vocab.token_bos()]).decode("utf-8", "ignore")
            if vocab.token_bos() >= 0
            else ""
        )
        self.fmt = Jinja2ChatFormatter(
            template=meta["tokenizer.chat_template"],
            eos_token=eos,
            bos_token=bos,
            add_generation_prompt=True,
        )

    def top(self, msgs: list[dict], k: int = 20) -> tuple[list[dict], int]:
        res = self.fmt(messages=msgs)
        toks = self.llm.tokenize(
            res.prompt.encode("utf-8"), add_bos=not res.added_special, special=True
        )
        self.llm.reset()
        self.llm.eval(toks)
        # With logits_all=False, llama-cpp-python 0.3.16 does not copy the last row into
        # Llama.scores, so read it from the context directly.
        ptr = self.llama_cpp.llama_get_logits_ith(self.llm._ctx.ctx, -1)
        logits = self.np.ctypeslib.as_array(ptr, shape=(self.llm.n_vocab(),)).astype(
            self.np.float64
        )
        logits -= logits.max()
        logp = logits - self.np.log(self.np.exp(logits).sum())
        idx = self.np.argpartition(-logp, k)[:k]
        idx = idx[self.np.argsort(-logp[idx])]
        out = [
            {
                "token": self.llm.detokenize([int(i)]).decode("utf-8", "ignore"),
                "logprob": float(logp[i]),
            }
            for i in idx
        ]
        return out, len(toks)


def one(scorer: Scorer, item: dict) -> dict:
    msgs, kind = prompt_for(item)
    e0 = time.time()
    c0, w0 = time.process_time(), time.perf_counter()
    top, n_prompt = scorer.top(msgs)
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    e1 = time.time()
    mass = label_mass(top, item["labels"])
    total = sum(mass.values())
    ranked = sorted(mass.items(), key=lambda kv: -kv[1])
    pred = ranked[0][0] if total > 0 else None
    norm = [v / total for _, v in ranked] if total > 0 else [0.0] * len(ranked)
    return {
        "item_id": item["id"],
        "domain": item["domain"],
        "phase": item["phase"],
        "kind": kind,
        "gold": item["answer"],
        "pred": pred,
        "correct": pred == item["answer"],
        "label_mass_total": round(total, 6),
        "p_max": round(norm[0], 6),
        "margin": round(norm[0] - (norm[1] if len(norm) > 1 else 0.0), 6),
        "prompt_tokens": n_prompt,
        "wall_s": round(wall, 6),
        "cpu_s": round(cpu, 6),
        "t_start_epoch": round(e0, 6),
        "t_end_epoch": round(e1, 6),
        "first_token": top[0]["token"] if top else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="configuration id from the protocol config")
    ap.add_argument("--tier", required=True, choices=["device", "edge"])
    ap.add_argument("--domains", required=True, help="comma-separated domain list")
    ap.add_argument("--phase", required=True, choices=["pilot", "confirmatory"])
    ap.add_argument("--protocol", type=Path, default=Path("configs/2026-10-17-mac-v1.json"))
    ap.add_argument("--items", type=Path, default=Path("data/items/items-v1.jsonl"))
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="testing only: first N items")
    ap.add_argument("--no-replay", action="store_true", help="skip the timing replay")
    args = ap.parse_args()

    from llama_cpp import Llama
    from llama_cpp import __version__ as llama_version

    proto = json.loads(args.protocol.read_text())
    cfg = next(c for c in proto["configurations"] if c["id"] == args.config)
    tier = proto["tiers"][args.tier]
    if args.tier not in cfg["tiers"]:
        print(f"{args.config} is not run on tier {args.tier}", file=sys.stderr)
        return 2
    all_items = [json.loads(x) for x in args.items.read_text().splitlines() if x]
    files = [args.models_dir / f for f in cfg["files"]]
    hashes = {f.name: sha256(f) for f in files}
    for f in cfg["files"]:
        if hashes[f] != cfg["sha256"][f]:
            raise SystemExit(f"checksum mismatch for {f}")

    c0, w0, e0 = time.process_time(), time.perf_counter(), time.time()
    llm = Llama(
        model_path=str(files[0]),
        n_ctx=proto["runtime"]["n_ctx"],
        n_threads=tier["threads"],
        n_threads_batch=tier["threads"],
        n_batch=proto["runtime"]["n_batch"],
        n_gpu_layers=tier["n_gpu_layers"],
        seed=0,
        verbose=False,
    )
    scorer = Scorer(llm)
    load = {
        "wall_s": round(time.perf_counter() - w0, 3),
        "cpu_s": round(time.process_time() - c0, 3),
        "t_start_epoch": round(e0, 3),
        "t_end_epoch": round(time.time(), 3),
    }
    args.out.mkdir(parents=True, exist_ok=True)

    for domain in args.domains.split(","):
        items = [i for i in all_items if i["domain"] == domain and i["phase"] == args.phase]
        if args.limit:
            items = items[: args.limit]
        stem = f"{args.config}__{args.tier}__{domain}__{args.phase}"
        rows_path = args.out / f"{stem}.jsonl"
        po0, therm0 = pageouts(), sh(["pmset", "-g", "therm"])
        main_start = time.time()
        with rows_path.open("w") as fh:
            for it in items:
                row = {"config": args.config, "tier": args.tier, **one(scorer, it)}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
        main_end = time.time()

        timing = []
        replay_start = replay_end = None
        if not args.no_replay:
            subset = items[:TIMING_SUBSET]
            for _ in range(WARMUP):
                for it in subset:
                    one(scorer, it)
            replay_start = time.time()
            for rep in range(REPS):
                for it in subset:
                    r = one(scorer, it)
                    timing.append(
                        {
                            "rep": rep,
                            "item_id": it["id"],
                            "wall_s": r["wall_s"],
                            "cpu_s": r["cpu_s"],
                            "t_start_epoch": r["t_start_epoch"],
                            "t_end_epoch": r["t_end_epoch"],
                            "prompt_tokens": r["prompt_tokens"],
                            "pred": r["pred"],
                        }
                    )
            replay_end = time.time()
            (args.out / f"{stem}.timing.jsonl").write_text(
                "".join(
                    json.dumps({"config": args.config, "tier": args.tier, **t}) + "\n"
                    for t in timing
                )
            )
        po1 = pageouts()
        manifest = {
            "stem": stem,
            "protocol_identity": proto["identity"],
            "config": cfg,
            "tier": {"name": args.tier, **tier},
            "domain": domain,
            "phase": args.phase,
            "n_items": len(items),
            "model_sha256": hashes,
            "load": load,
            "windows_epoch": {
                "main": [round(main_start, 6), round(main_end, 6)],
                "replay": [replay_start, replay_end],
            },
            "pageouts_before": po0,
            "pageouts_after": po1,
            "swapped": (po0 is not None and po1 is not None and po1 > po0),
            "thermal_before": therm0,
            "peak_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_rss_unit": "bytes" if platform.system() == "Darwin" else "kilobytes",
            "llama_cpp_python": llama_version,
            "host": cpu_info(),
            "rows_sha256": sha256(rows_path),
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (args.out / f"{stem}.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        rows = [json.loads(x) for x in rows_path.read_text().splitlines()]
        acc = sum(r["correct"] for r in rows) / max(1, len(rows))
        per_item = (main_end - main_start) / max(1, len(rows))
        print(
            json.dumps(
                {
                    "stem": stem,
                    "n": len(rows),
                    "accuracy": round(acc, 3),
                    "s_per_item": round(per_item, 4),
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
