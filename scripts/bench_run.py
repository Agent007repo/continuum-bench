"""Run one benchmark cell (model configuration x tier x domain shard) and write raw records.

Runs on a GitHub-hosted Linux runner or any Linux host with llama-cpp-python installed.
Each item gets one forward pass over the model's chat-formatted prompt. The answer is the
label with the highest probability mass among the top-20 next-token log probabilities,
so quality is scored automatically against the dataset's published label. We record wall
time, process CPU time (all threads), prompt tokens and peak resident memory. Energy is
NOT measured here: hosted runners expose no energy counters, so analysis derives an
estimate from CPU time (see the v1 protocol).

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
    if item["source"] == "pubmedqa":
        user = f"Abstract: {item['context']}\n\nQuestion: {item['question']}\nAnswer (yes, no or maybe):"
        return [
            {"role": "system", "content": SYSTEM["ynm"]},
            {"role": "user", "content": user},
        ], "ynm"
    opts = "\n".join(
        f"{lab}. {txt}" for lab, txt in zip(item["labels"], item["choices"], strict=True)
    )
    user = f"Question: {item['question']}\n{opts}\nAnswer:"
    return [{"role": "system", "content": SYSTEM["mc"]}, {"role": "user", "content": user}], "mc"


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


def cpu_info() -> dict:
    info = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "nproc": os.cpu_count(),
    }
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
    c0, w0 = time.process_time(), time.perf_counter()
    top, n_prompt = scorer.top(msgs)
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
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
        "first_token": top[0]["token"] if top else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="configuration id from the protocol config")
    ap.add_argument("--tier", required=True, choices=["device", "edge"])
    ap.add_argument("--domain", required=True)
    ap.add_argument("--phase", required=True, choices=["pilot", "confirmatory"])
    ap.add_argument("--protocol", type=Path, default=Path("configs/2026-10-17-cloud-v1.json"))
    ap.add_argument("--items", type=Path, default=Path("data/items/items-v1.jsonl"))
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="testing only: first N items")
    args = ap.parse_args()

    from llama_cpp import Llama
    from llama_cpp import __version__ as llama_version

    proto = json.loads(args.protocol.read_text())
    cfg = next(c for c in proto["configurations"] if c["id"] == args.config)
    tier = proto["tiers"][args.tier]
    if args.tier not in cfg["tiers"]:
        print(f"{args.config} is not run on tier {args.tier}", file=sys.stderr)
        return 2
    items = [json.loads(x) for x in args.items.read_text().splitlines() if x]
    items = [i for i in items if i["domain"] == args.domain and i["phase"] == args.phase]
    if args.limit:
        items = items[: args.limit]
    files = [args.models_dir / f for f in cfg["files"]]
    hashes = {f.name: sha256(f) for f in files}
    for f in cfg["files"]:
        if hashes[f] != cfg["sha256"][f]:
            raise SystemExit(f"checksum mismatch for {f}")

    c0, w0 = time.process_time(), time.perf_counter()
    llm = Llama(
        model_path=str(files[0]),
        n_ctx=proto["runtime"]["n_ctx"],
        n_threads=tier["threads"],
        n_threads_batch=tier["threads"],
        n_batch=proto["runtime"]["n_batch"],
        seed=0,
        verbose=False,
    )
    scorer = Scorer(llm)
    load = {
        "wall_s": round(time.perf_counter() - w0, 3),
        "cpu_s": round(time.process_time() - c0, 3),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.config}__{args.tier}__{args.domain}__{args.phase}"
    rows_path = args.out / f"{stem}.jsonl"
    with rows_path.open("w") as fh:
        for it in items:
            fh.write(
                json.dumps({"config": args.config, "tier": args.tier, **one(scorer, it)}) + "\n"
            )
            fh.flush()

    timing = []
    subset = items[:TIMING_SUBSET]
    for _ in range(WARMUP):
        for it in subset:
            one(scorer, it)
    for rep in range(REPS):
        for it in subset:
            r = one(scorer, it)
            timing.append(
                {
                    "rep": rep,
                    "item_id": it["id"],
                    "wall_s": r["wall_s"],
                    "cpu_s": r["cpu_s"],
                    "prompt_tokens": r["prompt_tokens"],
                    "pred": r["pred"],
                }
            )
    (args.out / f"{stem}.timing.jsonl").write_text(
        "".join(json.dumps({"config": args.config, "tier": args.tier, **t}) + "\n" for t in timing)
    )

    manifest = {
        "stem": stem,
        "config": cfg,
        "tier": {"name": args.tier, **tier},
        "domain": args.domain,
        "phase": args.phase,
        "n_items": len(items),
        "model_sha256": hashes,
        "load": load,
        "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "llama_cpp_python": llama_version,
        "host": cpu_info(),
        "git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "runner": {
            k: os.environ.get(k)
            for k in (
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "ImageVersion",
                "RUNNER_NAME",
            )
        },
        "rows_sha256": sha256(rows_path),
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (args.out / f"{stem}.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    acc = sum(json.loads(x)["correct"] for x in rows_path.read_text().splitlines()) / max(
        1, len(items)
    )
    print(json.dumps({"stem": stem, "n": len(items), "accuracy": round(acc, 3)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
