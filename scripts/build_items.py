"""Build the frozen v1 evaluation item set from pinned public dataset revisions.

Run once: uv run --with pyarrow --with huggingface_hub python scripts/build_items.py
Writes data/items/items-v1.jsonl and data/items/manifest.json. Items are short
multiple-choice or yes/no/maybe questions, so quality is scored automatically
against the datasets' published labels. Pilot items are disjoint from confirmatory items.
"""

import hashlib
import json
import random
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

root = Path(__file__).resolve().parents[1]
SEED = 20261017
SOURCES = {
    "mmlu": ("cais/mmlu", "c30699e8356da336a370243923dbaf21066bb9fe", "MIT"),
    "pubmedqa": ("qiaojin/PubMedQA", "9001f2853fb87cab8d220904e0de81ac6973b318", "MIT"),
    "arc": ("allenai/ai2_arc", "210d026faf9955653af8916fad021475a3f00453", "CC BY-SA 4.0"),
}
DOMAINS = {
    "healthcare": {
        "sensitivity": "special-category",
        "parts": [
            ("pubmedqa", "pqa_labeled/train-00000-of-00001.parquet", 90),
            ("mmlu", "clinical_knowledge/test-00000-of-00001.parquet", 30),
            ("mmlu", "college_medicine/test-00000-of-00001.parquet", 15),
            ("mmlu", "professional_medicine/test-00000-of-00001.parquet", 30),
        ],
    },
    "digital_industries": {
        "sensitivity": "confidential",
        "parts": [
            ("mmlu", "computer_security/test-00000-of-00001.parquet", 60),
            ("mmlu", "electrical_engineering/test-00000-of-00001.parquet", 60),
            ("mmlu", "college_computer_science/test-00000-of-00001.parquet", 45),
        ],
    },
    "general_control": {
        "sensitivity": "public",
        "parts": [("arc", "ARC-Challenge/test-00000-of-00001.parquet", 165)],
    },
}
PILOT_PER_DOMAIN = 15
LETTERS = "ABCDE"


def load(src: str, path: str) -> list[dict]:
    repo, rev, _ = SOURCES[src]
    local = hf_hub_download(repo, path, repo_type="dataset", revision=rev)
    return pq.read_table(local).to_pylist()


def to_item(src: str, path: str, row: dict, idx: int) -> dict | None:
    if src == "mmlu":
        return {
            "question": row["question"],
            "choices": list(row["choices"]),
            "labels": list(LETTERS[: len(row["choices"])]),
            "answer": LETTERS[int(row["answer"])],
            "source_row": idx,
        }
    if src == "arc":
        labels = [str(x) for x in row["choices"]["label"]]
        if labels != list(LETTERS[: len(labels)]):
            return None  # keep the A-D(E) items only; numeric-label items are skipped
        return {
            "question": row["question"],
            "choices": list(row["choices"]["text"]),
            "labels": labels,
            "answer": row["answerKey"],
            "source_row": idx,
        }
    if src == "pubmedqa":
        ctx = " ".join(row["context"]["contexts"])
        return {
            "question": row["question"],
            "context": ctx,
            "choices": ["yes", "no", "maybe"],
            "labels": ["yes", "no", "maybe"],
            "answer": row["final_decision"],
            "source_row": row["pubid"],
        }
    raise ValueError(src)


def main() -> None:
    rng = random.Random(SEED)
    items = []
    for domain, spec in DOMAINS.items():
        pool = []
        for src, path, n in spec["parts"]:
            rows = [to_item(src, path, r, i) for i, r in enumerate(load(src, path))]
            rows = [r for r in rows if r]
            picked = rng.sample(rows, n)
            for r in picked:
                r.update({"source": src, "source_file": path, "licence": SOURCES[src][2]})
            pool.extend(picked)
        rng.shuffle(pool)
        for k, r in enumerate(pool):
            r["domain"] = domain
            r["sensitivity"] = spec["sensitivity"]
            r["phase"] = "pilot" if k < PILOT_PER_DOMAIN else "confirmatory"
            r["id"] = f"{domain[:3].upper()}-{k:03d}"
        items.extend(pool)
    out = root / "data/items/items-v1.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in items))
    manifest = {
        "identity": "ContinuumBench/items/v1",
        "seed": SEED,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "sources": {
            k: {"repo": v[0], "revision": v[1], "licence": v[2]} for k, v in SOURCES.items()
        },
        "counts": {
            d: {
                p: sum(1 for r in items if r["domain"] == d and r["phase"] == p)
                for p in ("pilot", "confirmatory")
            }
            for d in DOMAINS
        },
    }
    (root / "data/items/manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest["counts"]), manifest["sha256"][:12])


if __name__ == "__main__":
    main()
